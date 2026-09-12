"""
Weekly job: checks whether the PM/PD planning Excel sheet itself has been
re-uploaded recently, and alerts admins/planners (never technicians - this
is a data-input problem, not a maintenance-task problem) if it hasn't.

This is distinct from the daily reminder job (app/jobs/reminder_jobs.py),
which only reminds people about PM dates *already in the database*. If the
plant stops re-uploading the planning sheet altogether, the daily job keeps
quietly reminding people about a stale schedule and nothing ever flags that
the source data itself has gone stale - this job closes that gap.

Two independent triggers, both admin-tunable via AppSetting (see
app.core.settings_service):
  1. STALENESS  - no completed import in `sheet_freshness_days` days at all
                  (default 35 - a little over a month, so a normal monthly
                  re-upload cadence never falsely triggers this).
  2. MONTH-END  - it's the `sheet_freshness_month_end_day`-th of the month
                  (default the 25th) or later, and there has been no
                  completed import *this calendar month* yet - catches the
                  "usually re-uploads monthly but hasn't done this month's
                  yet" case earlier than trigger 1 would.

Idempotency: reuses the ScheduledJob (job_type, period) unique-constraint
pattern from monthly_report_job.py, keyed per ISO week for STALENESS and
per calendar month for MONTH_END, so this can never double-alert even if
the scheduler restarts or two processes race.
"""

from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import ImportBatch, ScheduledJob
from app.notifications import templates
from app.notifications.notification_service import send_admin_alert
from app.core.settings_service import get_setting
from app.core.config import settings
from app.core.timeutils import today_local

STALENESS_JOB_TYPE = "SHEET_FRESHNESS_STALE"
MONTH_END_JOB_TYPE = "SHEET_FRESHNESS_MONTH_END"


def _latest_completed_import(db: Session) -> ImportBatch | None:
    return (
        db.query(ImportBatch)
        .filter(ImportBatch.status == "COMPLETED")
        .order_by(ImportBatch.uploaded_at.desc())
        .first()
    )


def _admin_whatsapp_numbers() -> list:
    return [p.strip() for p in settings.ADMIN_WHATSAPP_NUMBERS.split(",") if p.strip()]


def _claim(db: Session, job_type: str, period: str) -> bool:
    """Returns True if this process won the claim (i.e. should proceed)."""
    job = ScheduledJob(job_type=job_type, period=period, status="RUNNING",
                        started_at=datetime.utcnow())
    db.add(job)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _complete(db: Session, job_type: str, period: str, status: str, error: str = None):
    job = db.query(ScheduledJob).filter(
        ScheduledJob.job_type == job_type, ScheduledJob.period == period
    ).first()
    if job:
        job.status = status
        job.completed_at = datetime.utcnow()
        job.error_message = error
        db.commit()


def run_sheet_freshness_check(db: Session, today: date = None) -> dict:
    today = today or today_local()
    results = {"staleness_alert_sent": False, "month_end_alert_sent": False}

    threshold_days = get_setting(db, "sheet_freshness_days", 35)
    month_end_day = get_setting(db, "sheet_freshness_month_end_day", 25)

    latest = _latest_completed_import(db)
    latest_at = latest.uploaded_at if latest else None

    # --- Trigger 1: no import at all in `threshold_days` days ------------
    iso_year, iso_week, _ = today.isocalendar()
    stale_period = f"{iso_year:04d}-W{iso_week:02d}"
    is_stale = (latest_at is None) or ((today - latest_at.date()).days >= threshold_days)

    if is_stale and _claim(db, STALENESS_JOB_TYPE, stale_period):
        try:
            reason = (
                f"No PM planning sheet has ever been imported."
                if latest_at is None else
                f"No new import in {(today - latest_at.date()).days} days "
                f"(threshold: {threshold_days} days)."
            )
            body = templates.sheet_not_updated_alert(reason, latest_at, threshold_days)
            send_admin_alert(
                subject="PM Planning Sheet Not Updated - Action Needed",
                body=body,
                whatsapp_numbers=_admin_whatsapp_numbers(),
            )
            results["staleness_alert_sent"] = True
            _complete(db, STALENESS_JOB_TYPE, stale_period, "COMPLETED")
        except Exception as e:
            _complete(db, STALENESS_JOB_TYPE, stale_period, "FAILED", str(e))
            raise

    # --- Trigger 2: no import yet THIS calendar month, and we're past the
    #     configured "should have re-uploaded by now" day of the month ----
    month_period = f"{today.year:04d}-{today.month:02d}"
    imported_this_month = latest_at is not None and (
        latest_at.year == today.year and latest_at.month == today.month
    )
    past_month_end_day = today.day >= month_end_day

    if (not imported_this_month) and past_month_end_day and _claim(db, MONTH_END_JOB_TYPE, month_period):
        try:
            reason = (
                f"It's day {today.day} of the month and no planning sheet has been "
                f"imported for {today.strftime('%B %Y')} yet."
            )
            body = templates.sheet_not_updated_alert(reason, latest_at, threshold_days)
            send_admin_alert(
                subject=f"PM Planning Sheet Missing for {today.strftime('%B %Y')}",
                body=body,
                whatsapp_numbers=_admin_whatsapp_numbers(),
            )
            results["month_end_alert_sent"] = True
            _complete(db, MONTH_END_JOB_TYPE, month_period, "COMPLETED")
        except Exception as e:
            _complete(db, MONTH_END_JOB_TYPE, month_period, "FAILED", str(e))
            raise

    return results
