import os
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, require_roles
from app.core.audit import record_audit
from app.core.config import settings
from app.models.models import (
    PMPlan, PMActual, PMStatus, CompletionClass, Employee, Role, Machine,
    ChecklistTemplateItem, PMChecklistResponse, MachineResponsibility,
)
from app.schemas.schemas import PMPlanOut, PMCompleteIn
from app.core.timeutils import today_local
from app.storage import get_storage
from app.core.malware_scan import scan_bytes

router = APIRouter(prefix="/api/pm", tags=["pm"])

# Proof-of-work attachments (photo of the completed job, filled checklist,
# etc. — spec section 13), stored via the object storage abstraction
# (app/storage) so they survive redeploys/restarts and work across
# multiple API replicas (Critical #5 in the production review).
# PMActual.attachment_path stores a storage KEY, not a filesystem path.
ALLOWED_ATTACHMENT_EXT = {".jpg", ".jpeg", ".png", ".pdf", ".heic", ".webp"}
ALLOWED_ATTACHMENT_MIME = {
    "image/jpeg", "image/png", "image/heic", "image/webp", "application/pdf",
}
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024  # 15 MB


def _sniff_content_type(contents: bytes, fallback_ext: str) -> str:
    """Very small magic-byte check so we're not trusting the client's
    declared content_type or the filename extension alone (High Priority
    item: 'Attachment validation is extension-based'). This is not a
    substitute for real malware scanning (still recommended before this
    goes in front of the public internet) but it stops the trivial
    "malicious.exe renamed to .jpg" case from being accepted as an image."""
    if contents[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if contents[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if contents[:4] == b"%PDF":
        return "application/pdf"
    if contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "image/webp"
    if contents[:4] in (b"II*\x00", b"MM\x00*"):  # HEIC/TIFF-family container - permissive
        return "image/heic"
    raise HTTPException(400, "File content doesn't match an allowed attachment type")


@router.get("", response_model=list[PMPlanOut])
def list_pm(
    db: Session = Depends(get_db),
    status: str | None = None,
    machine_id: str | None = None,
    _user: Employee = Depends(get_current_user),
):
    q = db.query(PMPlan)
    if status:
        q = q.filter(PMPlan.status == status)
    if machine_id:
        q = q.filter(PMPlan.machine_id == machine_id)
    return q.order_by(PMPlan.planned_date).all()


@router.get("/upcoming", response_model=list[PMPlanOut])
def upcoming(db: Session = Depends(get_db), days: int = 14, _user: Employee = Depends(get_current_user)):
    today = today_local()
    return db.query(PMPlan).filter(
        PMPlan.planned_date >= today,
        PMPlan.planned_date <= today.fromordinal(today.toordinal() + days),
        PMPlan.status.notin_([PMStatus.COMPLETED, PMStatus.CANCELLED, PMStatus.PENDING_SUPERVISOR_CONFIRMATION]),
    ).order_by(PMPlan.planned_date).all()


@router.get("/overdue", response_model=list[PMPlanOut])
def overdue(db: Session = Depends(get_db), _user: Employee = Depends(get_current_user)):
    today = today_local()
    return db.query(PMPlan).filter(
        PMPlan.planned_date < today,
        PMPlan.status.notin_([PMStatus.COMPLETED, PMStatus.CANCELLED, PMStatus.PENDING_SUPERVISOR_CONFIRMATION]),
    ).order_by(PMPlan.planned_date).all()


@router.get("/pending-confirmation", response_model=list[PMPlanOut])
def pending_confirmation(
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles(Role.SUPERVISOR, Role.MANAGER, Role.ADMIN)),
):
    """
    Critical-machine completions a technician has submitted but that are
    still awaiting supervisor sign-off (PMStatus.PENDING_SUPERVISOR_
    CONFIRMATION). These are deliberately excluded from /upcoming and
    /overdue - those two are driven by `planned_date` vs today, which is
    meaningless once a technician has already submitted a completion - but
    per the model's own docstring they must still surface somewhere as an
    open, actionable item for supervisors, or a completed-but-unconfirmed
    critical job could silently sit forever. This is that surface (fixes
    the previously-real contradiction between the PMStatus docstring and
    every endpoint that read it).
    """
    return db.query(PMPlan).filter(
        PMPlan.status == PMStatus.PENDING_SUPERVISOR_CONFIRMATION,
    ).order_by(PMPlan.planned_date).all()


@router.get("/{pm_id}", response_model=PMPlanOut)
def get_pm(pm_id: str, db: Session = Depends(get_db), _user: Employee = Depends(get_current_user)):
    """
    Single PM plan lookup - needed by the completion screen so it can
    resolve machine_id and then fetch that machine's checklist template
    before rendering the form (Critical #3: "Checklist backend and
    frontend don't match").
    """
    plan = db.query(PMPlan).get(pm_id)
    if not plan:
        raise HTTPException(404, "PM plan not found")
    return plan


@router.post("/{pm_id}/complete")
async def complete_pm(
    pm_id: str,
    actual_date: date = Form(...),
    completed_by: str | None = Form(None),
    remarks: str | None = Form(None),
    delay_reason: str | None = Form(None),
    downtime_minutes: int | None = Form(None),
    checklist_responses: str | None = Form(None),  # JSON: [{"item_id": "...", "checked": true, "note": "..."}]
    attachment: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles(Role.TECHNICIAN, Role.SUPERVISOR, Role.MANAGER, Role.ADMIN)),
):
    """
    Marks a PM plan complete. Accepts multipart/form-data so a proof-of-work
    photo or scanned checklist can be attached in the same call (spec section
    13) — `attachment` is optional; JSON-only clients can simply omit it.

    If the machine has a checklist template assigned (Future-Ready item
    C.4: checklist-per-PM-type instead of a single done/not-done), every
    `required` item on that template must be checked or this call is
    rejected with 400 - a technician can't tick "PM complete" while
    skipping a mandatory sub-step, which is the whole point of moving off
    a single done/not-done flag.
    """
    import json as _json

    plan = db.query(PMPlan).get(pm_id)
    if not plan:
        raise HTTPException(404, "PM plan not found")

    # Business-rule validation (Medium: "PM completion should have
    # stronger validation") - a completion date in the future is never
    # legitimate for a technician self-reporting their own work; only
    # supervisors/managers/admins can override (e.g. correcting a
    # backdated entry against a known future maintenance window).
    if actual_date > today_local() and user.role == Role.TECHNICIAN:
        raise HTTPException(400, "Actual completion date cannot be in the future")
    if downtime_minutes is not None and downtime_minutes < 0:
        raise HTTPException(400, "downtime_minutes cannot be negative")

    # Object-level authorization: role alone only proves "a technician",
    # not "the technician responsible for THIS machine" (Critical #2 in the
    # production review). A technician may only complete a PM for a machine
    # they are actually assigned to (PMPlan.assigned_to) or hold a
    # MachineResponsibility for; supervisors/managers/admins can complete
    # any PM, since they already have broader authority.
    if user.role == Role.TECHNICIAN:
        is_assigned = plan.assigned_to == user.id
        if not is_assigned:
            is_assigned = db.query(MachineResponsibility).filter(
                MachineResponsibility.machine_id == plan.machine_id,
                MachineResponsibility.employee_id == user.id,
            ).first() is not None
        if not is_assigned:
            raise HTTPException(403, "You are not assigned to this machine's PM")

    machine = db.query(Machine).get(plan.machine_id)
    responses = _json.loads(checklist_responses) if checklist_responses else []
    if machine and machine.checklist_template_id:
        template_items = db.query(ChecklistTemplateItem).filter(
            ChecklistTemplateItem.template_id == machine.checklist_template_id
        ).all()
        checked_item_ids = {r["item_id"] for r in responses if r.get("checked")}
        missing_required = [i.text for i in template_items if i.required and i.id not in checked_item_ids]
        if missing_required:
            raise HTTPException(
                400,
                f"Cannot mark complete - required checklist item(s) not checked: {', '.join(missing_required)}",
            )

    old_status = plan.status.value if plan.status else None
    actual = db.query(PMActual).filter(PMActual.pm_plan_id == pm_id).first()
    is_new = actual is None

    # Completion modification policy (Medium: "PM modification semantics
    # need attention"): once a PM has been submitted, only a supervisor+
    # may correct it. A technician gets exactly one submission per PM -
    # if they made a mistake, a supervisor corrects or the technician asks
    # one to. This mirrors how confirm_pm already works (second set of
    # eyes for critical machines) rather than introducing a separate
    # policy just for edits. The full prior state is captured into
    # old_value below regardless of who's editing, so any correction -
    # even a legitimate supervisor one - is fully reconstructable from the
    # audit trail.
    if not is_new and user.role == Role.TECHNICIAN:
        raise HTTPException(
            403,
            "This PM has already been submitted and can no longer be edited by a technician. "
            "Ask a supervisor to make the correction.",
        )

    prior_actual_snapshot = None
    if not is_new:
        prior_actual_snapshot = {
            "actual_date": str(actual.actual_date) if actual.actual_date else None,
            "completed_by": actual.completed_by,
            "remarks": actual.remarks,
            "delay_reason": actual.delay_reason,
            "downtime_minutes": actual.downtime_minutes,
            "attachment_path": actual.attachment_path,
            "completion_class": actual.completion_class.value if actual.completion_class else None,
        }

    if not actual:
        actual = PMActual(pm_plan_id=pm_id)
        db.add(actual)

    actual.actual_date = actual_date
    # `completed_by` used to accept any client-supplied employee id
    # unconditionally (High Priority: "Actual completion authorization").
    # Now: only a supervisor/manager/admin may complete on behalf of
    # someone else; a technician can only complete their own work.
    if completed_by and completed_by != user.id:
        if user.role not in (Role.SUPERVISOR, Role.MANAGER, Role.ADMIN):
            raise HTTPException(403, "You are not permitted to complete a PM on behalf of another employee")
        actual.completed_by = completed_by
        actual.completed_on_behalf_by = user.id
    else:
        actual.completed_by = user.id
    actual.remarks = remarks
    actual.delay_reason = delay_reason
    actual.downtime_minutes = downtime_minutes
    db.flush()  # need actual.id before saving checklist responses

    if not is_new:
        db.query(PMChecklistResponse).filter(PMChecklistResponse.pm_actual_id == actual.id).delete()
    for r in responses:
        db.add(PMChecklistResponse(
            pm_actual_id=actual.id, checklist_template_item_id=r["item_id"],
            checked=bool(r.get("checked")), note=r.get("note"),
        ))

    if attachment is not None and attachment.filename:
        ext = os.path.splitext(attachment.filename)[1].lower()
        if ext not in ALLOWED_ATTACHMENT_EXT:
            raise HTTPException(400, f"Unsupported attachment type '{ext}'. Allowed: {sorted(ALLOWED_ATTACHMENT_EXT)}")
        contents = await attachment.read()
        if len(contents) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(400, "Attachment exceeds 15 MB limit.")
        content_type = _sniff_content_type(contents, ext)  # validates real content, not just extension/declared type
        scan_result = scan_bytes(contents, filename=attachment.filename)
        if scan_result["status"] == "infected":
            raise HTTPException(400, "Attachment failed malware scan and was rejected.")
        storage_key = f"attachments/{pm_id}/{uuid.uuid4().hex[:8]}{ext}"
        get_storage().put(storage_key, contents, content_type=content_type)
        # Deliberately NOT deleting the previous attachment_path here: if
        # db.commit() below fails, we'd have already deleted the old
        # object while the DB (post-rollback) still points at it - the
        # exact orphan/partial-completion failure mode flagged under
        # "Transaction handling around PM completion" in the production
        # review. Old attachments are cheap to keep around; a periodic
        # cleanup job can garbage-collect any key not referenced by a
        # current PMActual.attachment_path, once storage is committed to.
        actual.attachment_path = storage_key

    if plan.planned_date:
        delay = (actual_date - plan.planned_date).days
        actual.delay_days = delay
        actual.completion_class = (
            CompletionClass.ON_TIME if delay <= 0 else CompletionClass.LATE
        ) if delay >= 0 else CompletionClass.EARLY

    # Critical machines (`*`-flagged) need a second set of eyes: a technician
    # self-reporting completion only gets the job to PENDING_SUPERVISOR_
    # CONFIRMATION, not COMPLETED - closes the "self-reported completion"
    # accuracy gap the customer flagged. A supervisor/manager/admin acting
    # here (e.g. confirming on a technician's behalf) can complete directly,
    # since that already is the second set of eyes.
    machine = db.query(Machine).get(plan.machine_id)
    requires_sign_off = bool(machine and machine.critical and user.role == Role.TECHNICIAN)

    plan.status = PMStatus.PENDING_SUPERVISOR_CONFIRMATION if requires_sign_off else PMStatus.COMPLETED
    plan.completed_by_technician_id = user.id
    if not requires_sign_off:
        plan.confirmed_by_supervisor_id = user.id
        plan.confirmed_at = datetime.utcnow()
    db.commit()

    record_audit(
        db,
        action="PM_CREATED" if is_new else "PM_MODIFIED",
        entity_type="PMPlan",
        entity_id=pm_id,
        actor_id=user.id,
        old_value={"status": old_status, "prior_actual": prior_actual_snapshot},
        new_value={"status": plan.status.value, "actual_date": str(actual_date),
                   "completion_class": actual.completion_class.value if actual.completion_class else None,
                   "has_attachment": bool(actual.attachment_path)},
    )

    return {
        "success": True, "pm_id": pm_id,
        "status": plan.status.value,
        "completion_class": actual.completion_class,
        "has_attachment": bool(actual.attachment_path),
        "awaiting_supervisor_confirmation": requires_sign_off,
    }


@router.post("/{pm_id}/confirm")
def confirm_pm(
    pm_id: str,
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles(Role.SUPERVISOR, Role.MANAGER, Role.ADMIN)),
):
    """
    Supervisor sign-off step for critical-machine completions. Only moves a
    plan from PENDING_SUPERVISOR_CONFIRMATION -> COMPLETED; a supervisor
    can't rubber-stamp a job that was never marked done by a technician.
    """
    plan = db.query(PMPlan).get(pm_id)
    if not plan:
        raise HTTPException(404, "PM plan not found")
    if plan.status != PMStatus.PENDING_SUPERVISOR_CONFIRMATION:
        raise HTTPException(400, f"PM plan is not awaiting confirmation (status={plan.status.value}).")

    plan.status = PMStatus.COMPLETED
    plan.confirmed_by_supervisor_id = user.id
    plan.confirmed_at = datetime.utcnow()
    db.commit()

    record_audit(
        db, action="PM_MODIFIED", entity_type="PMPlan", entity_id=pm_id, actor_id=user.id,
        old_value={"status": "PENDING_SUPERVISOR_CONFIRMATION"},
        new_value={"status": "COMPLETED", "confirmed_by_supervisor_id": user.id},
    )
    return {"success": True, "pm_id": pm_id, "status": "COMPLETED"}


@router.get("/{pm_id}/attachment")
def get_attachment(
    pm_id: str,
    db: Session = Depends(get_db),
    _user: Employee = Depends(get_current_user),
):
    actual = db.query(PMActual).filter(PMActual.pm_plan_id == pm_id).first()
    if not actual or not actual.attachment_path:
        raise HTTPException(404, "No attachment for this PM completion")

    storage = get_storage()
    if not storage.exists(actual.attachment_path):
        raise HTTPException(404, "No attachment for this PM completion")

    # S3-compatible backends can hand the client a short-lived signed URL
    # directly - cheaper and faster than streaming the bytes through the
    # API process. Local disk has no such thing, so fall back to streaming.
    presigned = storage.url(actual.attachment_path, expires_seconds=settings.S3_PRESIGNED_URL_TTL_SECONDS)
    if presigned:
        return RedirectResponse(presigned)

    data = storage.get(actual.attachment_path)
    return StreamingResponse(iter([data]), media_type="application/octet-stream")
