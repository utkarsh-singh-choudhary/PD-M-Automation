from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.core.config import settings
from app.core.database import SessionLocal
from app.jobs.reminder_jobs import run_daily_reminder_job
from app.jobs.monthly_report_job import run_monthly_report_job
from app.jobs.data_freshness_job import run_sheet_freshness_check
from app.jobs.notification_retry_job import run_notification_retry_job
from app.jobs.attachment_cleanup_job import run_attachment_cleanup_job

tz = pytz.timezone(settings.TIMEZONE)
scheduler = BackgroundScheduler(timezone=tz)


def _daily_reminder_job():
    db = SessionLocal()
    try:
        run_daily_reminder_job(db)
    finally:
        db.close()


def _monthly_report_job():
    db = SessionLocal()
    try:
        run_monthly_report_job(db)
    finally:
        db.close()


def _sheet_freshness_job():
    db = SessionLocal()
    try:
        run_sheet_freshness_check(db)
    finally:
        db.close()


def _notification_retry_job():
    db = SessionLocal()
    try:
        run_notification_retry_job(db)
    finally:
        db.close()


def _attachment_cleanup_job():
    db = SessionLocal()
    try:
        run_attachment_cleanup_job(db)
    finally:
        db.close()


def start_scheduler():
    # Daily at 08:00 Asia/Kolkata - covers upcoming/due/overdue/escalation.
    scheduler.add_job(
        _daily_reminder_job,
        CronTrigger(hour=8, minute=0),
        id="daily_pm_reminders",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Monthly: 1st day of the month at 09:00 Asia/Kolkata, reports on the month just ended.
    scheduler.add_job(
        _monthly_report_job,
        CronTrigger(day=1, hour=9, minute=0),
        id="monthly_pm_report",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Daily at 08:30 Asia/Kolkata (30min after reminders) - cheap check, its
    # own ScheduledJob-based idempotency means it only actually alerts once
    # per week (staleness) or once per month (month-end-no-import), so a
    # daily cron is safe and catches both triggers promptly.
    scheduler.add_job(
        _sheet_freshness_job,
        CronTrigger(hour=8, minute=30),
        id="sheet_freshness_check",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Every 15 minutes - picks up anything sitting in RETRYING (High
    # Priority: "Notification retry mechanism isn't actually a full retry
    # queue"). Cheap no-op most runs since it only touches rows already
    # flagged RETRYING and due per backoff.
    scheduler.add_job(
        _notification_retry_job,
        CronTrigger(minute="*/15"),
        id="notification_retry",
        replace_existing=True,
        misfire_grace_time=600,
    )
    # Weekly, Sunday 02:00 - garbage-collects orphaned attachments past
    # retention (Medium: "Attachment lifecycle cleanup is missing"). Off
    # peak hours since it lists the whole attachments/ prefix.
    scheduler.add_job(
        _attachment_cleanup_job,
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id="attachment_cleanup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    return scheduler
