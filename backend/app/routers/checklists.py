from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles, get_current_user
from app.models.models import ChecklistTemplate, ChecklistTemplateItem, Machine, Employee, Role

router = APIRouter(prefix="/api/checklists", tags=["checklists"])

AdminRoles = require_roles(Role.ADMIN, Role.MANAGER)


@router.get("")
def list_templates(db: Session = Depends(get_db), _user: Employee = Depends(get_current_user)):
    templates = db.query(ChecklistTemplate).filter(ChecklistTemplate.active.is_(True)).all()
    return [
        {"id": t.id, "name": t.name, "description": t.description,
         "items": [{"id": i.id, "sequence": i.sequence, "text": i.text, "required": i.required}
                   for i in t.items]}
        for t in templates
    ]


@router.post("")
def create_template(
    name: str, description: str | None = None,
    items: list[dict] = None,  # [{"text": "...", "required": true}, ...] in order
    db: Session = Depends(get_db), _user: Employee = Depends(AdminRoles),
):
    template = ChecklistTemplate(name=name, description=description)
    db.add(template)
    db.flush()
    for idx, item in enumerate(items or []):
        db.add(ChecklistTemplateItem(
            template_id=template.id, sequence=idx,
            text=item["text"], required=item.get("required", True),
        ))
    db.commit()
    return {"id": template.id}


@router.post("/{template_id}/assign/{machine_id}")
def assign_template_to_machine(
    template_id: str, machine_id: str,
    db: Session = Depends(get_db), _user: Employee = Depends(AdminRoles),
):
    machine = db.query(Machine).get(machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    if not db.query(ChecklistTemplate).get(template_id):
        raise HTTPException(404, "Checklist template not found")
    machine.checklist_template_id = template_id
    db.commit()
    return {"machine_id": machine_id, "checklist_template_id": template_id}


@router.get("/for-machine/{machine_id}")
def get_template_for_machine(
    machine_id: str, db: Session = Depends(get_db), _user: Employee = Depends(get_current_user),
):
    """What the mobile 'complete PM' screen should render for this machine - empty items list if none assigned."""
    machine = db.query(Machine).get(machine_id)
    if not machine or not machine.checklist_template_id:
        return {"template_id": None, "items": []}
    template = db.query(ChecklistTemplate).get(machine.checklist_template_id)
    return {
        "template_id": template.id,
        "items": [{"id": i.id, "sequence": i.sequence, "text": i.text, "required": i.required}
                  for i in template.items],
    }
