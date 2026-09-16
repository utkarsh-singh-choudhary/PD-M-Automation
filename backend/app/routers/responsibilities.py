"""Machine <-> employee responsibility assignment. Determines who the
daily reminder job (app/jobs/reminder_jobs.py) actually notifies for a
given machine - importing a PM Excel sheet never touches this table,
since the sheet only carries machine/date data, not people."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.core.audit import record_audit
from app.models.models import Employee, Machine, MachineResponsibility, Role

router = APIRouter(prefix="/api/responsibilities", tags=["responsibilities"])

AdminOnly = require_roles(Role.ADMIN)


class AssignAllMachinesIn(BaseModel):
    employee_id: str
    responsibility_type: str = "PRIMARY"


@router.get("")
def list_responsibilities(db: Session = Depends(get_db), _user=Depends(AdminOnly)):
    rows = db.query(MachineResponsibility).all()
    return [
        {
            "id": r.id,
            "machine_id": r.machine_id,
            "employee_id": r.employee_id,
            "responsibility_type": r.responsibility_type,
        }
        for r in rows
    ]


@router.post("/assign-all-machines")
def assign_all_machines(
    payload: AssignAllMachinesIn, db: Session = Depends(get_db), user=Depends(AdminOnly)
):
    """Convenience bulk-assign: make one employee responsible for every
    active machine at the given level. Used for initial rollout when
    there's only one point of contact; per-machine reassignment can
    follow later via individual POST /api/responsibilities entries
    (not yet built - this endpoint covers the immediate bulk case)."""
    emp = db.query(Employee).get(payload.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")

    machines = db.query(Machine).filter(Machine.active.is_(True)).all()
    created = 0
    for m in machines:
        exists = (
            db.query(MachineResponsibility)
            .filter(
                MachineResponsibility.machine_id == m.id,
                MachineResponsibility.employee_id == emp.id,
                MachineResponsibility.responsibility_type == payload.responsibility_type,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            MachineResponsibility(
                machine_id=m.id,
                employee_id=emp.id,
                responsibility_type=payload.responsibility_type,
            )
        )
        created += 1
    db.commit()

    record_audit(
        db,
        action="RESPONSIBILITY_BULK_ASSIGNED",
        entity_type="Employee",
        entity_id=emp.id,
        actor_id=user.id,
        new_value={"machines_assigned": created, "responsibility_type": payload.responsibility_type},
    )
    return {"employee_id": emp.id, "machines_assigned": created, "total_active_machines": len(machines)}
