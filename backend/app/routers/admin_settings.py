from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.core.audit import record_audit
from app.core.settings_service import get_all_settings, set_setting, validate_setting, DESCRIPTIONS, DEFAULTS
from app.models.models import Employee, Role

router = APIRouter(prefix="/api/admin/settings", tags=["admin"])

AdminOnly = require_roles(Role.ADMIN)


class SettingUpdate(BaseModel):
    value: Any


@router.get("")
def list_settings(db: Session = Depends(get_db), _user: Employee = Depends(AdminOnly)):
    """Returns every tunable setting with its current (or default) value and description."""
    current = get_all_settings(db)
    return [
        {"key": key, "value": current.get(key, default), "default": default, "description": DESCRIPTIONS.get(key)}
        for key, default in DEFAULTS.items()
    ]


@router.put("/{key}")
def update_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db), user: Employee = Depends(AdminOnly)):
    if key not in DEFAULTS:
        # Was previously a 200 with an {"error": ...} body - a genuinely
        # unknown key is a client error, not a successful no-op (Medium:
        # "Admin settings API validation is weak").
        raise HTTPException(404, f"Unknown setting key '{key}'. Known keys: {list(DEFAULTS.keys())}")

    try:
        validated_value = validate_setting(key, payload.value)
    except ValueError as e:
        raise HTTPException(400, str(e))

    old = get_all_settings(db).get(key)
    row = set_setting(db, key, validated_value, updated_by=user.id)

    record_audit(
        db, action="SETTING_UPDATED", entity_type="AppSetting", entity_id=key,
        actor_id=user.id, old_value={"value": old}, new_value={"value": row.value},
    )
    return {"key": row.key, "value": row.value, "description": row.description}
