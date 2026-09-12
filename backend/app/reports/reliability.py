"""
MTBF/MTTR per machine (Future-Ready item C.3) - the metric that turns this
from a PM checklist tool into a real reliability system, once breakdown
events are being logged (see BreakdownEvent).

MTBF (mean time between failures): average hours between the START of one
breakdown and the START of the next, over the observed window.
MTTR (mean time to repair): average hours from breakdown_at to resumed_at,
for events that were actually repaired (excludes resulted_in_scrap_or_replace).
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import BreakdownEvent, Machine


@dataclass
class MachineReliability:
    machine_id: str
    machine_number: str
    machine_name: str
    breakdown_count: int = 0
    open_breakdowns: int = 0  # currently down (resumed_at is null)
    mtbf_hours: float | None = None
    mttr_hours: float | None = None
    events: list = field(default_factory=list)


def build_reliability_report(db: Session, machine_id: str | None = None) -> list[MachineReliability]:
    machines_q = db.query(Machine)
    if machine_id:
        machines_q = machines_q.filter(Machine.id == machine_id)

    results = []
    for machine in machines_q.all():
        events = (
            db.query(BreakdownEvent)
            .filter(BreakdownEvent.machine_id == machine.id)
            .order_by(BreakdownEvent.breakdown_at)
            .all()
        )
        if not events:
            continue

        r = MachineReliability(
            machine_id=machine.id, machine_number=machine.machine_number,
            machine_name=machine.machine_name, breakdown_count=len(events),
        )

        # MTBF: gaps between successive breakdown starts.
        starts = [e.breakdown_at for e in events]
        if len(starts) >= 2:
            gaps_hours = [
                (starts[i + 1] - starts[i]).total_seconds() / 3600
                for i in range(len(starts) - 1)
            ]
            r.mtbf_hours = round(sum(gaps_hours) / len(gaps_hours), 1)

        # MTTR: only events that resumed (not still down) and weren't a
        # scrap/replace (repair time isn't meaningful there).
        repair_durations = [
            (e.resumed_at - e.breakdown_at).total_seconds() / 3600
            for e in events
            if e.resumed_at is not None and not e.resulted_in_scrap_or_replace
        ]
        if repair_durations:
            r.mttr_hours = round(sum(repair_durations) / len(repair_durations), 1)

        r.open_breakdowns = sum(1 for e in events if e.resumed_at is None)
        r.events = [
            {
                "id": e.id, "breakdown_at": e.breakdown_at.isoformat(),
                "resumed_at": e.resumed_at.isoformat() if e.resumed_at else None,
                "cause": e.cause, "resulted_in_scrap_or_replace": e.resulted_in_scrap_or_replace,
            }
            for e in events
        ]
        results.append(r)

    # Worst MTBF (most failure-prone) first - null MTBF (only one event so
    # far) sorts last since there isn't enough data yet to judge it.
    results.sort(key=lambda r: (r.mtbf_hours is None, r.mtbf_hours or 0))
    return results
