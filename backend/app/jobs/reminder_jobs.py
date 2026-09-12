"""
Daily job: scans PMPlan rows and sends the appropriate reminder for each,
using idempotency keys so re-running the job (e.g. after a scheduler
restart) never double-sends. Designed to be called by APScheduler once a day
(see app/jobs/scheduler.py) - each function is also independently callable
for testing.

Escalation thresholds and reminder day-offsets are read from config here for
simplicity; in the admin panel (Phase 4) these become DB-backed settings
instead of constants.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.models import PMPlan, PMActual, Machine, MachineResponsibility, Employee, PMStatus, NotificationType
from app.notifications import templates
from app.notifications.notification_service import send_pm_notification
from app.core.settings_service import get_setting
from app.core.timeutils import today_local

# Hardcoded fallbacks only — the live values used by the job are read from
# AppSetting (admin panel) at the top of run_daily_reminder_job() below, so a
# plant manager can retune these without a code deploy.
REMINDER_DAYS_BEFORE = 7
DUE_TOMORROW_DAYS_BEFORE = 1

ESCALATION_LEVELS = [
    (1, ["PRIMARY"]),
    (3, ["PRIMARY", "SUPERVISOR"]),
    (7, ["PRIMARY", "SUPERVISOR", "MANAGER"]),
]


def _get_responsible_employees(db: Session, machine_id: str, types=("PRIMARY",)):
    q = db.query(Employee).join(MachineResponsibility).filter(
        MachineResponsibility.machine_id == machine_id,
        MachineResponsibility.responsibility_type.in_(types),
    )
    # Eligible if they can receive email OR WhatsApp - previously this
    # required email specifically, which silently dropped WhatsApp-only
    # technicians (common on the shop floor: phone but no company email).
    return [
        e for e in q.all()
        if (e.email and e.notification_email_enabled)
        or (e.phone and e.notification_whatsapp_enabled)
    ]


def run_daily_reminder_job(db: Session, today: date = None):
    today = today or today_local()
    results = {"upcoming": 0, "due_tomorrow": 0, "due_today": 0, "overdue": 0, "escalated": 0}

    # Admin-tunable — falls back to the module constants above if unset.
    reminder_days_before = get_setting(db, "reminder_days_before", REMINDER_DAYS_BEFORE)
    due_tomorrow_days_before = get_setting(db, "due_tomorrow_days_before", DUE_TOMORROW_DAYS_BEFORE)
    escalation_thresholds = get_setting(
        db, "escalation_thresholds",
        [{"days": d, "levels": levels} for d, levels in ESCALATION_LEVELS],
    )

    open_plans = db.query(PMPlan).filter(
        PMPlan.status.notin_([PMStatus.COMPLETED, PMStatus.CANCELLED, PMStatus.PENDING_SUPERVISOR_CONFIRMATION]),
        PMPlan.planned_date.isnot(None),
    ).all()

    for plan in open_plans:
        machine = db.query(Machine).get(plan.machine_id)
        actual = db.query(PMActual).filter(PMActual.pm_plan_id == plan.id).first()
        days_diff = (plan.planned_date - today).days

        recipients = _get_responsible_employees(db, plan.machine_id, ("PRIMARY",))

        if actual and actual.actual_date:
            continue  # already completed - nothing to remind

        if days_diff == reminder_days_before:
            _notify(db, plan, machine, recipients, NotificationType.UPCOMING_REMINDER,
                    "PM Reminder - Upcoming",
                    templates.upcoming_reminder(machine.machine_name, machine.machine_number,
                                                 plan.planned_date, machine.location, days_diff,
                                                 pm_plan_id=plan.id),
                    today)
            results["upcoming"] += 1

        elif days_diff == due_tomorrow_days_before:
            _notify(db, plan, machine, recipients, NotificationType.DUE_REMINDER,
                    "PM Due Tomorrow",
                    templates.due_tomorrow_reminder(machine.machine_name, machine.machine_number,
                                                     plan.planned_date, pm_plan_id=plan.id),
                    today)
            results["due_tomorrow"] += 1

        elif days_diff == 0:
            _notify(db, plan, machine, recipients, NotificationType.DUE_REMINDER,
                    "PM Due Today",
                    templates.due_today_not_updated(machine.machine_name, machine.machine_number,
                                                     plan.planned_date, pm_plan_id=plan.id),
                    today)
            plan.status = PMStatus.DUE
            results["due_today"] += 1

        elif days_diff < 0:
            days_overdue = -days_diff
            plan.status = PMStatus.OVERDUE
            _notify(db, plan, machine, recipients, NotificationType.OVERDUE_REMINDER,
                    "OVERDUE Preventive Maintenance",
                    templates.overdue_reminder(machine.machine_name, machine.machine_number,
                                                plan.planned_date, days_overdue, pm_plan_id=plan.id),
                    today)
            results["overdue"] += 1

            for entry in escalation_thresholds:
                threshold, levels = entry["days"], entry["levels"]
                if days_overdue == threshold:
                    esc_recipients = _get_responsible_employees(db, plan.machine_id, tuple(levels))
                    _notify(db, plan, machine, esc_recipients, NotificationType.ESCALATION,
                            f"PM Escalation - {days_overdue} days overdue",
                            templates.escalation_notice(machine.machine_name, machine.machine_number,
                                                         plan.planned_date, days_overdue, len(levels),
                                                         pm_plan_id=plan.id),
                            today)
                    results["escalated"] += 1

    db.commit()
    return results


def _notify(db, plan, machine, recipients, notif_type, subject, body, today):
    for emp in recipients:
        send_pm_notification(
            db=db,
            pm_plan_id=plan.id,
            recipient_email=emp.email,
            recipient_id=emp.id,
            notification_type=notif_type,
            subject=subject,
            body=body,
            scheduled_date=today,
            employee=emp,
        )
