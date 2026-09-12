import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.core.audit import record_audit
from app.models.models import Employee, Role, PendingUpload
from app.importer.import_service import run_import
from app.storage import get_storage
from app.core.malware_scan import scan_bytes

router = APIRouter(prefix="/api/import", tags=["import"])

UPLOAD_EXPIRY = timedelta(hours=6)
MAX_IMPORT_FILE_SIZE = 25 * 1024 * 1024  # 25MB - see High Priority "File upload security"

ImportRoles = require_roles(Role.ADMIN, Role.MANAGER)

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}


def _resolve_upload(db: Session, upload_id: str, user: Employee) -> PendingUpload:
    """Look up a PendingUpload row and enforce ownership + expiry. Raises 404
    for anything that isn't a valid, unexpired upload owned by this user -
    same response whether the id is wrong, expired, or belongs to someone
    else, so this can't be used to probe for valid ids."""
    record = db.query(PendingUpload).filter(PendingUpload.id == upload_id).first()
    if not record or record.uploaded_by != user.id or record.expires_at < datetime.utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found or expired")
    if not get_storage().exists(record.stored_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found or expired")
    return record


@router.post("/excel/upload")
async def upload_excel(file: UploadFile = File(...), user: Employee = Depends(ImportRoles), db: Session = Depends(get_db)):
    """Step 1: upload the file, get back an opaque upload_id to use in preview/commit.
    The client never sees or supplies a filesystem path (Critical #4 fix).
    Stored via the object storage abstraction (Critical #6 fix) so it
    survives redeploys and works across multiple API replicas."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only .xlsx/.xlsm files are accepted")

    upload_id = str(uuid.uuid4())
    storage_key = f"excel_uploads/{upload_id}{ext}"

    chunks = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_IMPORT_FILE_SIZE:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                 f"File exceeds {MAX_IMPORT_FILE_SIZE // (1024*1024)}MB limit")
        chunks.append(chunk)
    contents = b"".join(chunks)

    # Malware scan before this file ever reaches storage or the openpyxl
    # parser (High Priority: "File upload still needs malware scanning").
    # Excel files are a classic macro/exploit vector, so this matters even
    # more here than for PM attachment images/PDFs.
    scan_result = scan_bytes(contents, filename=file.filename)
    if scan_result["status"] == "infected":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload failed malware scan and was rejected.")

    get_storage().put(
        storage_key, contents,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    record = PendingUpload(
        id=upload_id,
        original_filename=file.filename,
        stored_path=storage_key,
        uploaded_by=user.id,
        expires_at=datetime.utcnow() + UPLOAD_EXPIRY,
    )
    db.add(record)
    record_audit(db, action="EXCEL_UPLOADED", entity_type="ImportBatch", actor_id=user.id,
                 new_value={"filename": file.filename})
    db.commit()
    return {"upload_id": upload_id, "original_filename": file.filename}


@router.post("/excel/preview")
def preview_excel(
    upload_id: str = Form(...),
    sheet_name: str = Form(...),
    financial_year: str = Form(...),
    db: Session = Depends(get_db),
    user: Employee = Depends(ImportRoles),
):
    """Step 4-5: parse + diff against DB, WITHOUT writing anything."""
    record = _resolve_upload(db, upload_id, user)
    file_bytes = get_storage().get(record.stored_path)
    return run_import(
        db=db, file_bytes=file_bytes,
        original_filename=record.original_filename, sheet_name=sheet_name,
        financial_year=financial_year, preview=True,
    )


@router.post("/excel/bulk-commit")
def bulk_commit_excel(
    upload_id: str = Form(...),
    sheets: str = Form(...),  # JSON list like [{"sheet_name": "PM Plan-23-24", "financial_year": "23-24"}, ...]
    db: Session = Depends(get_db),
    user: Employee = Depends(ImportRoles),
):
    """
    Import several years' sheets from the same workbook in one call (e.g.
    PM Plan-23-24 / 24-25 / 25-26 / 26-27), so historical Plan-vs-Actual
    variance can be computed across years instead of just the current one.
    Each sheet still goes through the exact same single-sheet diff/commit
    logic as `/excel/commit` - this just loops it and returns one summary
    per sheet, plus which ones failed, rather than requiring N separate
    calls from the client.
    """
    import json
    record = _resolve_upload(db, upload_id, user)
    try:
        sheet_specs = json.loads(sheets)
        if not isinstance(sheet_specs, list) or not sheet_specs:
            raise ValueError("expected a non-empty JSON list")
        for spec in sheet_specs:
            if "sheet_name" not in spec or "financial_year" not in spec:
                raise ValueError("each sheet entry needs sheet_name and financial_year")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid 'sheets' payload: {e}")
    if len(sheet_specs) > 20:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many sheets in one request (max 20)")
    file_bytes = get_storage().get(record.stored_path)

    results = []
    for spec in sheet_specs:
        sheet_name = spec["sheet_name"]
        financial_year = spec["financial_year"]
        try:
            result = run_import(
                db=db, file_bytes=file_bytes,
                original_filename=record.original_filename, sheet_name=sheet_name,
                financial_year=financial_year, uploaded_by=user.id, preview=False,
            )
            record_audit(db, action="EXCEL_SYNCHRONIZED", entity_type="ImportBatch",
                         entity_id=result.get("import_batch_id"), actor_id=user.id,
                         new_value={k: v for k, v in result.items() if k != "preview_rows"})
            results.append({"sheet_name": sheet_name, "financial_year": financial_year,
                             "success": True, "summary": result})
        except Exception as e:
            # One bad sheet (wrong name, unexpected layout) shouldn't abort
            # the sheets already committed before it - each sheet's writes
            # are already committed inside run_import, so we just record
            # the failure and move on to the next sheet.
            results.append({"sheet_name": sheet_name, "financial_year": financial_year,
                             "success": False, "error": str(e)})

    return {"results": results}


@router.post("/excel/commit")
def commit_excel(
    upload_id: str = Form(...),
    sheet_name: str = Form(...),
    financial_year: str = Form(...),
    db: Session = Depends(get_db),
    user: Employee = Depends(ImportRoles),
):
    """Step 6-7: commit the previously previewed import."""
    record = _resolve_upload(db, upload_id, user)
    file_bytes = get_storage().get(record.stored_path)
    result = run_import(
        db=db, file_bytes=file_bytes,
        original_filename=record.original_filename, sheet_name=sheet_name,
        financial_year=financial_year, uploaded_by=user.id, preview=False,
    )
    record_audit(db, action="EXCEL_SYNCHRONIZED", entity_type="ImportBatch",
                 entity_id=result.get("import_batch_id"), actor_id=user.id,
                 new_value={k: v for k, v in result.items() if k != "preview_rows"})
    # Commit is terminal for this upload - clean up so storage doesn't
    # accumulate and the upload_id can't be replayed against commit again.
    get_storage().delete(record.stored_path)
    db.delete(record)
    db.commit()
    return result
