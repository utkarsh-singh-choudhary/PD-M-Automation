from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.core.audit import record_audit
from app.models.models import BreakdownEvent, Employee, Role
from app.reports.reliability import build_reliability_report

router = APIRouter(prefix="/api/breakdowns", tags=["breakdowns"])

LogRoles = require_roles(Role.TECHNICIAN, Role.SUPERVISOR, Role.MANAGER, Role.ADMIN)
ViewRoles = require_roles(Role.ADMIN, Role.MANAGER, Role.SUPERVISOR, Role.VIEWER)


@router.post("")
def report_breakdown(
    machine_id: str,
    breakdown_at: datetime,
    cause: str | None = None,
    db: Session = Depends(get_db),
    user: Employee = Depends(LogRoles),
):
    """Log the start of a breakdown. `resumed_at` is filled in later via /{id}/resolve."""
    event = BreakdownEvent(machine_id=machine_id, breakdown_at=breakdown_at,
                           cause=cause, reported_by=user.id)
    db.add(event)
    db.commit()
    record_audit(db, action="BREAKDOWN_REPORTED", entity_type="BreakdownEvent",
                 entity_id=event.id, actor_id=user.id,
                 new_value={"machine_id": machine_id, "breakdown_at": str(breakdown_at)})
    return {"id": event.id, "machine_id": machine_id, "breakdown_at": str(breakdown_at)}


@router.post("/{event_id}/resolve")
def resolve_breakdown(
    event_id: str,
    resumed_at: datetime,
    action_taken: str | None = None,
    resulted_in_scrap_or_replace: bool = False,
    db: Session = Depends(get_db),
    user: Employee = Depends(LogRoles),
):
    event = db.query(BreakdownEvent).get(event_id)
    if not event:
        raise HTTPException(404, "Breakdown event not found")
    event.resumed_at = resumed_at
    event.action_taken = action_taken
    event.resulted_in_scrap_or_replace = resulted_in_scrap_or_replace
    event.repaired_by = user.id
    db.commit()
    record_audit(db, action="BREAKDOWN_RESOLVED", entity_type="BreakdownEvent",
                 entity_id=event_id, actor_id=user.id,
                 new_value={"resumed_at": str(resumed_at), "resulted_in_scrap_or_replace": resulted_in_scrap_or_replace})
    return {"id": event.id, "resumed_at": str(resumed_at)}


@router.get("/reliability")
def get_reliability_report(machine_id: str | None = None, db: Session = Depends(get_db), _user=Depends(ViewRoles)):
    """MTBF/MTTR per machine - see app/reports/reliability.py."""
    reports = build_reliability_report(db, machine_id=machine_id)
    return {
        "machines": [
            {
                "machine_id": r.machine_id, "machine_number": r.machine_number,
                "machine_name": r.machine_name, "breakdown_count": r.breakdown_count,
                "open_breakdowns": r.open_breakdowns,
                "mtbf_hours": r.mtbf_hours, "mttr_hours": r.mttr_hours,
                "events": r.events,
            }
            for r in reports
        ]
    }
