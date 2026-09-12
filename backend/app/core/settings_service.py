"""
DB-backed admin settings, with hardcoded fallbacks so the system behaves
identically to before this existed if nothing has been configured yet.

Usage:
    from app.core.settings_service import get_setting
    reminder_days = get_setting(db, "reminder_days_before", default=7)

Keys that the admin panel exposes (see app/routers/admin_settings.py):
    reminder_days_before        int   - days before due date to send "upcoming" reminder
    due_tomorrow_days_before    int   - days before due date to send "due tomorrow" reminder
    escalation_thresholds       list[{"days": int, "levels": [str]}] - overdue escalation ladder
    week_band_size_days         int   - locked week->date convention band width (default 7)
    week_start_offset_days      int   - day-of-month the W1 band starts on (default 1)
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import AppSetting

DEFAULTS: dict[str, Any] = {
    "reminder_days_before": 7,
    "due_tomorrow_days_before": 1,
    "escalation_thresholds": [
        {"days": 1, "levels": ["PRIMARY"]},
        {"days": 3, "levels": ["PRIMARY", "SUPERVISOR"]},
        {"days": 7, "levels": ["PRIMARY", "SUPERVISOR", "MANAGER"]},
    ],
    "week_band_size_days": 7,
    "week_start_offset_days": 1,
    "sheet_freshness_days": 35,
    "sheet_freshness_month_end_day": 25,
    "attachment_retention_days": 365,
}

DESCRIPTIONS: dict[str, str] = {
    "reminder_days_before": "Days before the planned date to send the first 'upcoming' reminder.",
    "due_tomorrow_days_before": "Days before the planned date to send the 'due tomorrow' reminder.",
    "escalation_thresholds": "Overdue escalation ladder: list of {days, levels[]} — who gets notified at each threshold.",
    "week_band_size_days": "Locked business rule: width (in days) of each W1-W5 band when converting week codes to calendar dates.",
    "week_start_offset_days": "Day-of-month that band W1 starts on (normally 1).",
    "sheet_freshness_days": "If no Excel import has happened in this many days, alert admins/planners to re-upload the PM plan sheet.",
    "sheet_freshness_month_end_day": "Day of the current month by which, if no import has happened yet THIS month, admins get a re-upload nudge.",
    "attachment_retention_days": "How many days an orphaned (unreferenced) attachment is kept in storage before the cleanup job deletes it.",
}


# Per-key validation (Medium: "Admin settings API validation is weak" -
# the endpoint previously accepted `value: Any` with no type/range check
# at all, so e.g. reminder_days_before could be set to -5, "banana", or a
# 10MB blob). Raises ValueError with a human-readable message on failure;
# routers/admin_settings.py turns that into a 400.
def _validate_int_range(value: Any, lo: int, hi: int, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{key}' must be an integer")
    if not (lo <= value <= hi):
        raise ValueError(f"'{key}' must be between {lo} and {hi}")
    return value


def _validate_escalation_thresholds(value: Any, key: str) -> Any:
    valid_levels = {"PRIMARY", "SUPERVISOR", "MANAGER"}
    if not isinstance(value, list) or not value:
        raise ValueError(f"'{key}' must be a non-empty list")
    for entry in value:
        if not isinstance(entry, dict) or "days" not in entry or "levels" not in entry:
            raise ValueError(f"'{key}' entries must look like {{'days': int, 'levels': [str]}}")
        _validate_int_range(entry["days"], 1, 365, f"{key}.days")
        if not isinstance(entry["levels"], list) or not entry["levels"]:
            raise ValueError(f"'{key}' entries need a non-empty 'levels' list")
        for lvl in entry["levels"]:
            if lvl not in valid_levels:
                raise ValueError(f"'{key}' has unknown level '{lvl}' - must be one of {sorted(valid_levels)}")
    return value


VALIDATORS = {
    "reminder_days_before": lambda v: _validate_int_range(v, 1, 60, "reminder_days_before"),
    "due_tomorrow_days_before": lambda v: _validate_int_range(v, 0, 7, "due_tomorrow_days_before"),
    "week_band_size_days": lambda v: _validate_int_range(v, 1, 31, "week_band_size_days"),
    "week_start_offset_days": lambda v: _validate_int_range(v, 1, 28, "week_start_offset_days"),
    "sheet_freshness_days": lambda v: _validate_int_range(v, 1, 365, "sheet_freshness_days"),
    "sheet_freshness_month_end_day": lambda v: _validate_int_range(v, 1, 28, "sheet_freshness_month_end_day"),
    "attachment_retention_days": lambda v: _validate_int_range(v, 1, 3650, "attachment_retention_days"),
    "escalation_thresholds": lambda v: _validate_escalation_thresholds(v, "escalation_thresholds"),
}


def validate_setting(key: str, value: Any) -> Any:
    """Raises ValueError on invalid input; returns the (possibly coerced) value on success."""
    validator = VALIDATORS.get(key)
    if validator is None:
        return value  # no validator registered - accept as-is (shouldn't happen for known keys)
    return validator(value)


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is not None:
        return row.value
    if default is not None:
        return default
    return DEFAULTS.get(key)


def get_all_settings(db: Session) -> dict[str, Any]:
    stored = {row.key: row.value for row in db.query(AppSetting).all()}
    merged = dict(DEFAULTS)
    merged.update(stored)
    return merged


def set_setting(db: Session, key: str, value: Any, updated_by: str = None) -> AppSetting:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        row = AppSetting(key=key, description=DESCRIPTIONS.get(key))
        db.add(row)
    row.value = value
    row.updated_by = updated_by
    db.commit()
    db.refresh(row)
    return row
