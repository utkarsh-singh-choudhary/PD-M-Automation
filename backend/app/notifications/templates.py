"""
Message templates for PM notifications.

Every template function returns a dict with three variants:
  "text"     - plain-text body, used for SMTP/M365/Gmail plain fallback
  "html"     - branded HTML body (used for email when the active provider
               supports HTML; all three current providers do)
  "whatsapp" - short-form body for WhatsApp (WhatsApp renders long
               multi-line text awkwardly and shop-floor readers want the
               essentials only: machine, date, and what to do)

Every variant that concerns a specific PM plan includes a direct
"Mark PM Complete" link (settings.APP_URL + /pm/{id}/complete) so the
recipient does not have to open the app and search for the machine -
this was flagged as a usability gap in the professional-polish review.
"""

from app.core.config import settings

COMPANY_NAME = settings.COMPANY_NAME or "Preventive Maintenance System"

_BRAND_COLOR = "#0f4c81"
_WARN_COLOR = "#b45309"
_DANGER_COLOR = "#b91c1c"


def _complete_link(pm_plan_id) -> str:
    if not pm_plan_id:
        return ""
    base = settings.APP_URL.rstrip("/")
    return f"{base}/pm/{pm_plan_id}/complete"


def _html_shell(title: str, accent: str, rows: dict, footer_note: str, pm_plan_id=None) -> str:
    link = _complete_link(pm_plan_id)
    rows_html = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#555;font-size:13px;">{label}</td>'
        f'<td style="padding:4px 0;font-size:14px;font-weight:600;color:#111;">{value}</td></tr>'
        for label, value in rows.items()
    )
    button_html = (
        f'<a href="{link}" style="display:inline-block;margin-top:18px;padding:10px 20px;'
        f'background:{accent};color:#fff;text-decoration:none;border-radius:6px;'
        f'font-size:14px;font-weight:600;">Mark PM Complete</a>'
        if link else ""
    )
    return f"""\
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:0 auto;
            border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
  <div style="background:{accent};padding:14px 20px;">
    <span style="color:#fff;font-size:13px;letter-spacing:.04em;text-transform:uppercase;">
      {COMPANY_NAME}
    </span>
  </div>
  <div style="padding:20px;">
    <h2 style="margin:0 0 14px 0;font-size:17px;color:#111;">{title}</h2>
    <table cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {rows_html}
    </table>
    {button_html}
    <p style="margin-top:18px;font-size:12px;color:#888;">{footer_note}</p>
  </div>
</div>
"""


def upcoming_reminder(machine_name, machine_number, planned_date, location=None,
                       days_remaining=None, pm_plan_id=None):
    text = (
        "PREVENTIVE MAINTENANCE REMINDER\n\n"
        f"Machine: {machine_name}\n"
        f"Machine No: {machine_number}\n"
        + (f"Location: {location}\n" if location else "")
        + f"Planned PM Date: {planned_date}\n"
        + (f"Days Remaining: {days_remaining}\n" if days_remaining is not None else "")
        + "\nPlease ensure the preventive maintenance activity is completed as scheduled."
        + (f"\n\nMark complete: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    rows = {"Machine": f"{machine_name} ({machine_number})", "Planned PM Date": str(planned_date)}
    if location:
        rows["Location"] = location
    if days_remaining is not None:
        rows["Days Remaining"] = str(days_remaining)
    html = _html_shell("Upcoming PM Reminder", _BRAND_COLOR, rows,
                        "This is an automated reminder — no action needed if the PM is already scheduled.",
                        pm_plan_id)
    whatsapp = (
        f"🔧 *PM Reminder*\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Due: {planned_date}"
        + (f" ({days_remaining}d left)" if days_remaining is not None else "")
        + (f"\nUpdate: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}


def due_tomorrow_reminder(machine_name, machine_number, planned_date, pm_plan_id=None):
    text = (
        "PM DUE TOMORROW\n\n"
        f"Machine: {machine_name}\n"
        f"Machine No: {machine_number}\n"
        f"Planned PM Date: {planned_date}\n\n"
        "Please complete/update the PM activity."
        + (f"\n\nMark complete: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    rows = {"Machine": f"{machine_name} ({machine_number})", "Planned PM Date": str(planned_date)}
    html = _html_shell("PM Due Tomorrow", _WARN_COLOR, rows,
                        "Please complete or update this PM before end of day tomorrow.", pm_plan_id)
    whatsapp = (
        f"⏰ *PM Due Tomorrow*\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Date: {planned_date}"
        + (f"\nUpdate: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}


def due_today_not_updated(machine_name, machine_number, planned_date, pm_plan_id=None):
    text = (
        "PM DUE TODAY - NOT YET UPDATED\n\n"
        f"Machine: {machine_name}\n"
        f"Machine No: {machine_number}\n"
        f"Planned PM Date: {planned_date}\n\n"
        "No actual completion has been recorded yet. Please update the status."
        + (f"\n\nMark complete: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    rows = {"Machine": f"{machine_name} ({machine_number})", "Planned PM Date": str(planned_date)}
    html = _html_shell("PM Due Today — Not Yet Updated", _WARN_COLOR, rows,
                        "No completion has been recorded for this PM yet.", pm_plan_id)
    whatsapp = (
        f"⚠️ *PM Due Today*\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Not yet marked complete."
        + (f"\nUpdate: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}


def overdue_reminder(machine_name, machine_number, planned_date, days_overdue, pm_plan_id=None):
    text = (
        "OVERDUE PM\n\n"
        f"Machine: {machine_number}\n"
        f"Machine Name: {machine_name}\n"
        f"Planned PM Date: {planned_date}\n"
        f"Days Overdue: {days_overdue}\n\n"
        "PM completion has not been recorded.\n"
        "Please update the maintenance status immediately."
        + (f"\n\nMark complete: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    rows = {
        "Machine": f"{machine_name} ({machine_number})",
        "Planned PM Date": str(planned_date),
        "Days Overdue": str(days_overdue),
    }
    html = _html_shell("OVERDUE Preventive Maintenance", _DANGER_COLOR, rows,
                        "This PM is overdue. Please update the status immediately.", pm_plan_id)
    whatsapp = (
        f"🔴 *PM OVERDUE — {days_overdue}d*\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Was due: {planned_date}"
        + (f"\nUpdate now: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}


def escalation_notice(machine_name, machine_number, planned_date, days_overdue, level, pm_plan_id=None):
    text = (
        f"ESCALATION - LEVEL {level}\n\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Planned PM Date: {planned_date}\n"
        f"Days Overdue: {days_overdue}\n\n"
        "This preventive maintenance activity remains incomplete and has been "
        "escalated per the configured escalation policy."
        + (f"\n\nMark complete: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    rows = {
        "Machine": f"{machine_name} ({machine_number})",
        "Planned PM Date": str(planned_date),
        "Days Overdue": str(days_overdue),
        "Escalation Level": str(level),
    }
    html = _html_shell(f"Escalation — Level {level}", _DANGER_COLOR, rows,
                        "This PM has been escalated per policy. Please resolve or reassign.", pm_plan_id)
    whatsapp = (
        f"🚨 *Escalation L{level} — {days_overdue}d overdue*\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Due was: {planned_date}"
        + (f"\nUpdate: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}


def generic_retry_notice(machine_name, machine_number, planned_date, original_notification_type, pm_plan_id=None):
    """Used by jobs/notification_retry_job.py to re-send a notification
    whose original attempt failed. Doesn't try to reconstruct the exact
    original copy (upcoming/due/overdue read differently) - just makes it
    unambiguous to the recipient that this is a delayed re-delivery of a
    real PM notification, not a duplicate spam message."""
    text = (
        "PM NOTIFICATION (RETRY)\n\n"
        f"Machine: {machine_name}\n"
        f"Machine No: {machine_number}\n"
        f"Planned PM Date: {planned_date}\n\n"
        f"This is a retried delivery of a {original_notification_type.replace('_', ' ').title()} "
        "notification that failed to send earlier."
        + (f"\n\nMark complete: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    rows = {"Machine": f"{machine_name} ({machine_number})", "Planned PM Date": str(planned_date),
            "Notification Type": original_notification_type.replace("_", " ").title()}
    html = _html_shell("PM Notification (Retry)", _WARN_COLOR, rows,
                        "This is a retried delivery - the original send attempt failed.", pm_plan_id)
    whatsapp = (
        f"🔁 *PM Notification (Retry)*\n"
        f"Machine: {machine_name} ({machine_number})\n"
        f"Date: {planned_date}"
        + (f"\nUpdate: {_complete_link(pm_plan_id)}" if pm_plan_id else "")
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}


def sheet_not_updated_alert(reason: str, last_import_at, threshold_days: int):
    """Sent to planners/admins (not technicians) when the PM planning
    Excel sheet itself hasn't been re-uploaded recently — distinct from a
    per-machine overdue reminder, which only fires for plans already in
    the database."""
    last_str = last_import_at.strftime("%d-%b-%Y") if last_import_at else "never"
    text = (
        "PM PLANNING SHEET NOT UPDATED\n\n"
        f"Reason: {reason}\n"
        f"Last Excel import: {last_str}\n"
        f"Freshness threshold: {threshold_days} days\n\n"
        "Please re-upload the current PM/PD planning sheet via the Import "
        "screen so upcoming reminders reflect the latest schedule."
    )
    rows = {"Reason": reason, "Last Import": last_str, "Threshold": f"{threshold_days} days"}
    html = _html_shell("Planning Sheet Not Updated", _WARN_COLOR, rows,
                        "Re-upload the latest planning workbook via Import so schedules stay accurate.")
    whatsapp = (
        f"📋 *Planning sheet not updated*\n"
        f"{reason}\n"
        f"Last import: {last_str}\n"
        f"Please re-upload the PM plan sheet."
    )
    return {"text": text, "html": html, "whatsapp": whatsapp}
