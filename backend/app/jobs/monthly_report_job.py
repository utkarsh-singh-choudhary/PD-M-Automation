"""
Monthly job: generates the PM performance report (PDF) for the just-ended
month and emails it to the configured recipients. Scheduled per spec section
15 (e.g. 1st day of next month at 09:00), wired in scheduler.py.

Idempotency: guarded by a ScheduledJob row keyed on
(job_type="MONTHLY_REPORT", period="YYYY-MM"). The row is inserted and
committed BEFORE any report generation/emailing happens, so if two scheduler
processes race (or the cron fires twice due to a misfire replay), the
UNIQUE(job_type, period) constraint lets exactly one of them through - the
loser catches the IntegrityError and returns without emailing anything.
"""

from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import ScheduledJob
from app.notifications.base import EmailMessage, EmailAttachment
from app.notifications.notification_service import get_active_email_provider
from app.reports.report_engine import build_monthly_report
from app.reports.report_render import render_pdf, render_excel
from app.core.timeutils import today_local

JOB_TYPE = "MONTHLY_REPORT"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _previous_month_and_fy(today: date):
    prev_month_num = today.month - 1 or 12
    prev_month_year = today.year if today.month != 1 else today.year - 1
    month_name = MONTH_NAMES[prev_month_num - 1]

    # financial year runs Apr-Mar; label like "26-27"
    if prev_month_num >= 4:
        fy_start = prev_month_year
    else:
        fy_start = prev_month_year - 1
    fy_label = f"{str(fy_start)[-2:]}-{str(fy_start + 1)[-2:]}"
    period = f"{prev_month_year:04d}-{prev_month_num:02d}"
    return month_name, fy_label, period


def run_monthly_report_job(db: Session, today: date = None):
    """Idempotency wrapper: claims the ScheduledJob row via an early commit
    (so the claim is durable and visible to other processes immediately),
    then delegates the actual report build/send to
    _generate_and_send_report()."""
    today = today or today_local()
    month_name, fy_label, period = _previous_month_and_fy(today)

    job = ScheduledJob(job_type=JOB_TYPE, period=period, status="RUNNING",
                        started_at=datetime.utcnow())
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # Another process already claimed (or already ran) this period.
        db.rollback()
        return {"generated": False, "emailed": False,
                "reason": f"{JOB_TYPE}:{period} already claimed/run"}

    try:
        result = _generate_and_send_report(db, month_name, fy_label)
        job.status = "COMPLETED"
        job.completed_at = datetime.utcnow()
        db.commit()
        return result
    except Exception as e:
        job.status = "FAILED"
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()
        raise


def _generate_and_send_report(db: Session, month_name: str, fy_label: str):
    report = build_monthly_report(db, month_name, fy_label)
    pdf_path = render_pdf(report)
    excel_path = render_excel(report)

    recipients = [r.strip() for r in settings.REPORT_RECIPIENTS.split(",") if r.strip()]
    if not recipients:
        return {"generated": True, "emailed": False, "reason": "No REPORT_RECIPIENTS configured",
                 "pdf_path": pdf_path, "excel_path": excel_path}

    provider = get_active_email_provider()
    subject = f"PM Performance Report - {month_name} {fy_label}"
    body = (
        f"Preventive Maintenance Performance Report\n\n"
        f"Month: {month_name} {fy_label}\n\n"
        f"Total PM Planned: {report.total_planned}\n"
        f"PM Completed: {report.completed}\n"
        f"Pending: {report.pending}\n"
        f"Overdue: {report.overdue}\n\n"
        f"Completion Rate: {report.completion_rate}%\n"
        f"On-Time Completion: {report.on_time_rate}%\n"
        f"Late Completion: {report.late_rate}%\n\n"
        f"Full report attached as PDF and Excel."
    )

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    with open(excel_path, "rb") as f:
        excel_bytes = f.read()

    attachments = [
        EmailAttachment(
            filename=f"pm_report_{month_name}_{fy_label}.pdf",
            content=pdf_bytes, mime_type="application/pdf",
        ),
        EmailAttachment(
            filename=f"pm_report_{month_name}_{fy_label}.xlsx",
            content=excel_bytes,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ]

    for recipient in recipients:
        provider.send(EmailMessage(to=recipient, subject=subject, body=body, attachments=attachments))

    return {"generated": True, "emailed": True, "recipients": recipients,
             "pdf_path": pdf_path, "excel_path": excel_path}
