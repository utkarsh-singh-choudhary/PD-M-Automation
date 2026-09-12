"""
Lets an external scheduler trigger the same jobs scheduler_main.py runs on
a cron, over plain HTTP - for deployments where there's no budget for an
always-on background worker (e.g. Render's free tier only offers free WEB
services, not free background workers). The intended caller is a GitHub
Actions scheduled workflow (see .github/workflows/pm-cron.yml), which is
free for public repos and has a generous free minutes allowance for
private ones.

Auth: a shared secret in the X-Cron-Secret header, NOT a user JWT -
GitHub Actions has no user session to log in with, so this is deliberately
a separate, simpler auth path from the rest of the API. Every endpoint
403s if CRON_SECRET is unset in the environment, so these are inert by
default and only usable once you've deliberately opted in by setting a
secret.

If you DO have budget for an always-on worker (Render paid plan, a VPS,
etc.), use scheduler_main.py instead and skip this entirely - both do the
same underlying job functions, just triggered differently (a persistent
in-process cron vs. an external HTTP trigger), so use one or the other,
not both, to avoid double-sends. The jobs are idempotent either way, so
accidentally running both is not silently harmful (see NotificationLog /
ScheduledJob unique-constraint idempotency in each job module) - but there's
no reason to bother.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.jobs.reminder_jobs import run_daily_reminder_job
from app.jobs.monthly_report_job import run_monthly_report_job
from app.jobs.data_freshness_job import run_sheet_freshness_check
from app.jobs.notification_retry_job import run_notification_retry_job
from app.jobs.attachment_cleanup_job import run_attachment_cleanup_job

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _verify_secret(x_cron_secret: str = Header(default=None)):
    if not settings.CRON_SECRET:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CRON_SECRET is not configured on the server")
    if not x_cron_secret or x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or missing X-Cron-Secret header")


@router.post("/daily-reminders")
def trigger_daily_reminders(db: Session = Depends(get_db), _=Depends(_verify_secret)):
    run_daily_reminder_job(db)
    return {"status": "ok", "job": "daily-reminders"}


@router.post("/monthly-report")
def trigger_monthly_report(db: Session = Depends(get_db), _=Depends(_verify_secret)):
    run_monthly_report_job(db)
    return {"status": "ok", "job": "monthly-report"}


@router.post("/sheet-freshness")
def trigger_sheet_freshness(db: Session = Depends(get_db), _=Depends(_verify_secret)):
    result = run_sheet_freshness_check(db)
    return {"status": "ok", "job": "sheet-freshness", **result}


@router.post("/notification-retry")
def trigger_notification_retry(db: Session = Depends(get_db), _=Depends(_verify_secret)):
    result = run_notification_retry_job(db)
    return {"status": "ok", "job": "notification-retry", **result}


@router.post("/attachment-cleanup")
def trigger_attachment_cleanup(db: Session = Depends(get_db), _=Depends(_verify_secret)):
    result = run_attachment_cleanup_job(db)
    return {"status": "ok", "job": "attachment-cleanup", **result}
