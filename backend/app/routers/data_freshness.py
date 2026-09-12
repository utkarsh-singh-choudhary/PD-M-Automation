"""
Manual trigger for the sheet-freshness check, so an Admin can test/verify
the "planning sheet not updated" alert without waiting for the 08:30 cron
(or for a real staleness/month-end condition to occur naturally).

Note: this calls the SAME idempotent function the scheduler calls, so if
an alert for the current week/month has already fired, running this again
will report `{"staleness_alert_sent": false, "month_end_alert_sent": false}`
rather than sending a duplicate - that's expected, not a bug. To force a
fresh test send, use a different DB (or clear the relevant ScheduledJob row).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.models.models import Role, Employee
from app.jobs.data_freshness_job import run_sheet_freshness_check

router = APIRouter(prefix="/api/admin/data-freshness", tags=["admin"])

AdminOnly = require_roles(Role.ADMIN)


@router.post("/check-now")
def trigger_freshness_check(db: Session = Depends(get_db), _user: Employee = Depends(AdminOnly)):
    return run_sheet_freshness_check(db)
