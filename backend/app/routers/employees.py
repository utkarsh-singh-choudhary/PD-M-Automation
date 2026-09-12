from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.core.security import hash_password
from app.core.audit import record_audit
from app.models.models import Employee, Role

router = APIRouter(prefix="/api/employees", tags=["employees"])

AdminOnly = require_roles(Role.ADMIN)


class EmployeeIn(BaseModel):
    name: str
    email: str
    password: str
    role: Role = Role.TECHNICIAN
    department: str | None = None
    designation: str | None = None
    phone: str | None = None


@router.get("")
def list_employees(db: Session = Depends(get_db), _user=Depends(AdminOnly)):
    return db.query(Employee).all()


@router.post("")
def create_employee(payload: EmployeeIn, db: Session = Depends(get_db), user=Depends(AdminOnly)):
    # Normalize so "Abc@x.com" and "abc@x.com" are treated as the same
    # login identity, and so the DB-level unique constraint on email
    # actually catches case-only duplicates.
    normalized_email = payload.email.strip().lower()
    emp = Employee(
        name=payload.name,
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
        designation=payload.designation,
        phone=payload.phone,
    )
    db.add(emp)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An employee with this email already exists")
    record_audit(db, action="EMPLOYEE_CREATED", entity_type="Employee", entity_id=emp.id,
                 actor_id=user.id, new_value={"email": emp.email, "role": emp.role.value})
    return {"id": emp.id, "name": emp.name, "email": emp.email, "role": emp.role}
