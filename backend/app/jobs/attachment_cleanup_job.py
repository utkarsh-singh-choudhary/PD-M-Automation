"""
Periodic job: garbage-collects attachment objects in storage that are no
longer referenced by any PMActual (Medium item: "Attachment lifecycle
cleanup is missing"). PM completion deliberately never deletes the
*previous* attachment when a new one is uploaded (see the comment in
routers/pm.py) so a failed commit can't leave the DB pointing at a deleted
object - but that means old attachment versions accumulate in storage
forever unless something eventually cleans them up. This is that
something.

Safety rules:
  - Only ever deletes objects under the "attachments/" prefix - never
    touches "excel_uploads/" (that already has its own expiry via
    PendingUpload).
  - Only deletes objects older than RETENTION_DAYS, so an attachment still
    mid-upload/mid-transaction is never at risk.
  - Only deletes a key if it does NOT match any PMActual.attachment_path -
    i.e. it's a genuinely orphaned object (an old version, or a completion
    whose attachment was later replaced), not the current attachment.
  - Every deletion is written to AuditLog so the cleanup itself is
    traceable, not a silent background delete.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.settings_service import get_setting
from app.models.models import PMActual
from app.storage import get_storage

RETENTION_DAYS_DEFAULT = 365  # keep a year of attachments unless overridden


def run_attachment_cleanup_job(db: Session) -> dict:
    retention_days = get_setting(db, "attachment_retention_days", RETENTION_DAYS_DEFAULT)

    referenced_keys = {
        row[0] for row in db.query(PMActual.attachment_path).filter(
            PMActual.attachment_path.isnot(None)
        ).all()
    }

    storage = get_storage()
    candidates = storage.list_with_age("attachments/")

    deleted, skipped_recent, skipped_referenced = [], 0, 0
    for obj in candidates:
        key = obj["key"]
        if key in referenced_keys:
            skipped_referenced += 1
            continue
        if obj["age_days"] < retention_days:
            skipped_recent += 1
            continue
        storage.delete(key)
        deleted.append(key)

    if deleted:
        record_audit(
            db,
            action="ATTACHMENTS_CLEANED_UP",
            entity_type="Storage",
            new_value={"deleted_count": len(deleted), "deleted_keys": deleted[:50],
                       "retention_days": retention_days, "run_at": datetime.utcnow().isoformat()},
        )

    return {
        "deleted_count": len(deleted),
        "skipped_recent": skipped_recent,
        "skipped_referenced": skipped_referenced,
        "retention_days": retention_days,
    }
