"""
Timezone-aware "today"/"now" helpers.

The bug this fixes: `date.today()` and `datetime.now()` (no tz) use
whatever timezone the *server process* is running in - which in a Docker
container is UTC unless someone remembered to set TZ. This plant is in
India (settings.TIMEZONE = "Asia/Kolkata", UTC+5:30). Around the midnight
IST boundary specifically - roughly 18:30-23:59 UTC - a server running in
UTC computes a `date.today()` that is *one day behind* IST's actual date.
For this system that means: reminders that should fire "today" fire a day
late (or the escalation/overdue math is off by a day) for ~5.5 hours every
single day, silently, forever - the kind of bug that never throws an error
and just quietly erodes trust in the automation.

Everywhere business logic asks "what date is it" for planning/reminders/
reports, it must go through here, not date.today()/datetime.now().

`datetime.utcnow()` remains correct and unchanged for pure timestamps that
aren't about a business "day" (created_at/updated_at audit columns, JWT
expiry, notification sent_at) - those are fine in UTC and out of scope
for this fix.
"""

from datetime import datetime, date
from zoneinfo import ZoneInfo

from app.core.config import settings

PLANT_TZ = ZoneInfo(settings.TIMEZONE)


def now_local() -> datetime:
    """Current timezone-aware datetime in the plant's local timezone."""
    return datetime.now(PLANT_TZ)


def today_local() -> date:
    """Current calendar date in the plant's local timezone (IST by default)."""
    return now_local().date()
