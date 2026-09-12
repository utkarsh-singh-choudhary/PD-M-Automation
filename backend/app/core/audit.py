"""
Central place to write AuditLog rows. Call this from any endpoint/job that
performs a meaningful state change, so "who changed this and when" is always
answerable (per spec section 18).
"""

from sqlalchemy.orm import Session

from app.models.models import AuditLog


def record_audit(
    db: Session,
    action: str,
    entity_type: str = None,
    entity_id: str = None,
    actor_id: str = None,
    old_value: dict = None,
    new_value: dict = None,
    ip_address: str = None,
    commit: bool = True,
):
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    )
    db.add(log)
    if commit:
        db.commit()
    return log
