"""
Periodic job that actually retries notifications sitting in RETRYING
(High Priority: "Notification retry mechanism isn't actually a full retry
queue" - send_pm_notification bumps retry_count and sets RETRYING on
failure, but nothing was ever coming back to pick those rows up again).

Backoff schedule, keyed by how many attempts have already been made
(retry_count): 1 min, 5 min, 30 min - matching the ideal sketched in the
original review. Re-delivery re-uses the same NotificationLog row's
recipient/type, and re-fetches the current PMPlan/Employee data rather
than trusting anything cached on the log row, since plenty of time may
have passed since the original attempt (e.g. the PM might have been
completed in the meantime, in which case there's no reason to keep
retrying a stale reminder).
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.models import (
    NotificationLog, DeliveryStatus, PMPlan, PMActual, Machine, Employee,
)
from app.notifications import templates
from app.notifications.notification_service import send_pm_notification, MAX_RETRIES

BACKOFF_MINUTES = {1: 1, 2: 5, 3: 30}  # retry_count -> minutes since last attempt before retrying


def _due_for_retry(log: NotificationLog, now: datetime) -> bool:
    wait_minutes = BACKOFF_MINUTES.get(log.retry_count, BACKOFF_MINUTES[max(BACKOFF_MINUTES)])
    last_attempt = log.sent_at or log.created_at
    if last_attempt is None:
        return True
    return now - last_attempt >= timedelta(minutes=wait_minutes)


def run_notification_retry_job(db: Session, now: datetime = None) -> dict:
    now = now or datetime.utcnow()
    retrying = db.query(NotificationLog).filter(
        NotificationLog.delivery_status == DeliveryStatus.RETRYING,
        NotificationLog.retry_count < MAX_RETRIES,
    ).all()

    attempted, skipped_not_due, skipped_stale = 0, 0, 0

    for log in retrying:
        if not _due_for_retry(log, now):
            skipped_not_due += 1
            continue

        plan = db.query(PMPlan).get(log.pm_plan_id)
        if not plan:
            skipped_stale += 1
            continue

        actual = db.query(PMActual).filter(PMActual.pm_plan_id == plan.id).first()
        if actual and actual.actual_date:
            # The underlying job got done since the original reminder
            # failed to send - retrying a "please do this PM" reminder for
            # already-completed work would be actively confusing, so drop
            # it rather than force it out.
            log.delivery_status = DeliveryStatus.FAILED
            log.error_message = "Skipped retry: PM was completed before the retry ran."
            db.commit()
            skipped_stale += 1
            continue

        machine = db.query(Machine).get(plan.machine_id)
        employee = db.query(Employee).get(log.recipient_id)
        if not machine or not employee or not employee.email:
            skipped_stale += 1
            continue

        # Rebuild the same notification body the original send used - the
        # notification_type on the log row tells us which template applies.
        body = templates.generic_retry_notice(
            machine.machine_name, machine.machine_number, plan.planned_date, log.notification_type.value,
        )
        send_pm_notification(
            db=db,
            pm_plan_id=plan.id,
            recipient_email=employee.email,
            recipient_id=employee.id,
            notification_type=log.notification_type,
            subject=f"[Retry] PM Notification - {machine.machine_number}",
            body=body,
            scheduled_date=plan.planned_date or now.date(),
            employee=employee,
        )
        attempted += 1

    return {
        "retrying_total": len(retrying),
        "attempted": attempted,
        "skipped_not_due": skipped_not_due,
        "skipped_stale": skipped_stale,
    }
