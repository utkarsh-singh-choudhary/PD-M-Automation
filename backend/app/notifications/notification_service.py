"""
Central notification service. Business logic (reminder jobs, escalation jobs)
call `notification_service.send_pm_notification(...)` - they never talk to a
provider directly. This is what lets M365 and Gmail (and later WhatsApp/SMS)
be swapped or run side by side without touching reminder/escalation logic.

Idempotency: every notification is keyed by
    f"{pm_plan_id}:{notification_type}:{scheduled_date}:{recipient_id}:{channel}"
so a scheduler restart or duplicate job run cannot send the same reminder
twice - we check NotificationLog for that key first. The key MUST include
recipient_id: without it, two different recipients for the same plan/type/
date (e.g. PRIMARY + SUPERVISOR on an escalation) collide on the same key,
and only the first recipient ever gets notified. It also includes channel
so a WhatsApp->email fallback for one recipient doesn't collide with a key
already used for that recipient's WhatsApp attempt.
"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import NotificationLog, NotificationType, NotificationChannel, DeliveryStatus
from app.notifications.base import EmailMessage
from app.notifications.providers.m365_provider import Microsoft365Provider
from app.notifications.providers.gmail_provider import GmailProvider
from app.notifications.providers.smtp_provider import SmtpGenericProvider
from app.notifications.providers.whatsapp_provider import WhatsAppProvider

PROVIDER_REGISTRY = {
    "m365": Microsoft365Provider,
    "gmail": GmailProvider,
    "smtp_generic": SmtpGenericProvider,
}

MAX_RETRIES = 3


def get_active_email_provider():
    provider_cls = PROVIDER_REGISTRY.get(settings.EMAIL_PROVIDER, SmtpGenericProvider)
    return provider_cls()


def pick_channel_for_employee(employee) -> NotificationChannel:
    """
    WhatsApp first, then email - not SMS, and not configurable per-message.
    For Indian shop-floor technicians, WhatsApp response/read rates run well
    above email (and above SMS, which isn't wired up at all here), so any
    employee with a phone number and notification_whatsapp_enabled gets
    WhatsApp; everyone else falls back to email.
    """
    if getattr(employee, "notification_whatsapp_enabled", False) and getattr(employee, "phone", None):
        return NotificationChannel.WHATSAPP
    return NotificationChannel.EMAIL


def build_idempotency_key(
    pm_plan_id: str,
    notification_type: NotificationType,
    scheduled_date: date,
    recipient_id: str,
    channel: NotificationChannel,
) -> str:
    return (
        f"{pm_plan_id}:{notification_type.value}:{scheduled_date.isoformat()}:"
        f"{recipient_id}:{channel.value}"
    )


def send_pm_notification(
    db: Session,
    pm_plan_id: str,
    recipient_email: str,
    recipient_id: str,
    notification_type: NotificationType,
    subject: str,
    body,
    scheduled_date: date,
    cc: list = None,
    employee=None,
) -> NotificationLog:
    """
    `employee` (optional, but pass it from new call sites) lets this pick
    WhatsApp over email via pick_channel_for_employee(); when omitted, it
    behaves exactly as before and always sends email, so existing callers
    that don't have the Employee object handy keep working unchanged.

    `body` accepts either a plain string (legacy call sites, unchanged
    behavior) or a dict as returned by app.notifications.templates.*()
    with "text"/"html"/"whatsapp" keys - the right variant is picked per
    channel below so WhatsApp gets the short-form copy and email gets the
    branded HTML version with a plain-text fallback.
    """
    channel = pick_channel_for_employee(employee) if employee is not None else NotificationChannel.EMAIL

    if isinstance(body, dict):
        text_body = body.get("text", "")
        html_body = body.get("html")
        whatsapp_body = body.get("whatsapp", text_body)
    else:
        text_body, html_body, whatsapp_body = body, None, body

    idempotency_key = build_idempotency_key(
        pm_plan_id, notification_type, scheduled_date, recipient_id, channel
    )

    existing = db.query(NotificationLog).filter(
        NotificationLog.idempotency_key == idempotency_key
    ).first()
    if existing and existing.delivery_status == DeliveryStatus.SENT:
        return existing  # already sent - do nothing, guarantees no duplicate sends

    log = existing or NotificationLog(
        pm_plan_id=pm_plan_id,
        recipient_id=recipient_id,
        notification_type=notification_type,
        channel=channel,
        idempotency_key=idempotency_key,
        delivery_status=DeliveryStatus.PENDING,
        retry_count=0,
    )
    if not existing:
        db.add(log)
        db.flush()

    if not settings.NOTIFICATIONS_ENABLED:
        log.delivery_status = DeliveryStatus.FAILED
        log.error_message = "Notifications globally disabled via config."
        db.commit()
        return log

    if channel == NotificationChannel.WHATSAPP:
        provider = WhatsAppProvider()
        log.provider = provider.name
        result = provider.send(to_phone=employee.phone, body=whatsapp_body)
        if not result["success"]:
            # Fall back to email rather than just failing the reminder
            # outright - a technician missing a WhatsApp send should still
            # get *something*, and it keeps the "email always works" bar
            # this system had before WhatsApp was added.
            log.channel = NotificationChannel.EMAIL
            provider = get_active_email_provider()
            log.provider = provider.name
            result = provider.send(EmailMessage(to=recipient_email, subject=subject,
                                                 body=text_body, html_body=html_body, cc=cc))
    else:
        provider = get_active_email_provider()
        log.provider = provider.name
        result = provider.send(EmailMessage(to=recipient_email, subject=subject,
                                             body=text_body, html_body=html_body, cc=cc))

    if result["success"]:
        log.delivery_status = DeliveryStatus.SENT
        log.sent_at = datetime.utcnow()
        log.error_message = None
    else:
        log.retry_count += 1
        log.error_message = result["error"]
        log.delivery_status = (
            DeliveryStatus.RETRYING if log.retry_count < MAX_RETRIES else DeliveryStatus.FAILED
        )

    db.commit()
    return log


def send_admin_alert(subject: str, body: dict, whatsapp_numbers: list = None) -> dict:
    """
    Fire-and-log an alert that isn't tied to a specific PM plan (e.g. the
    "planning sheet hasn't been re-uploaded" nudge) - so it can't go through
    send_pm_notification(), which requires a pm_plan_id for its idempotency
    key and NotificationLog row. Callers are responsible for their own
    idempotency (see app/jobs/data_freshness_job.py, which uses a
    ScheduledJob row per period so this never double-fires).

    `body` is a templates.*() dict ("text"/"html"/"whatsapp"). Sent to every
    address in settings.REPORT_RECIPIENTS by email, and additionally to
    `whatsapp_numbers` (E.164 phone strings) if provided and WhatsApp is
    configured. Returns a summary dict of what was actually sent - never
    raises, matching the "providers never raise" contract used elsewhere.
    """
    recipients = [r.strip() for r in settings.REPORT_RECIPIENTS.split(",") if r.strip()]
    text_body, html_body, whatsapp_body = body.get("text", ""), body.get("html"), body.get("whatsapp")

    email_results = []
    if settings.NOTIFICATIONS_ENABLED and recipients:
        provider = get_active_email_provider()
        for r in recipients:
            email_results.append(provider.send(
                EmailMessage(to=r, subject=subject, body=text_body, html_body=html_body)
            ))

    whatsapp_results = []
    if settings.NOTIFICATIONS_ENABLED and whatsapp_numbers and whatsapp_body:
        wa_provider = WhatsAppProvider()
        for phone in whatsapp_numbers:
            whatsapp_results.append(wa_provider.send(to_phone=phone, body=whatsapp_body))

    return {
        "email_recipients": recipients,
        "email_sent": sum(1 for r in email_results if r.get("success")),
        "whatsapp_sent": sum(1 for r in whatsapp_results if r.get("success")),
        "notifications_enabled": settings.NOTIFICATIONS_ENABLED,
    }
