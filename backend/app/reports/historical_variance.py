"""
Historical Plan-vs-Actual variance analysis (accuracy-improvements item 3).

Once multiple financial years' sheets are imported (see
import_router.bulk_commit_excel), each PMPlan already carries its own
`financial_year`, so this is a straightforward group-by - no separate
"historical" table or backfill needed. This module just aggregates
per-machine, per-year completion/on-time stats and flags machines whose
on-time rate is consistently poor across years, which is a lot more useful
for spotting a chronically-missed machine than any single year's numbers.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.models import PMPlan, PMActual, Machine, CompletionClass, PMStatus

# A machine counts as "chronically missed" if, across the years it has
# data for, its on-time rate is below this threshold in at least this many
# years. Both are business-tunable, not wired to AppSetting yet.
CHRONIC_ON_TIME_THRESHOLD = 60.0
CHRONIC_MIN_YEARS = 2


@dataclass
class YearStats:
    financial_year: str
    total_planned: int = 0
    completed: int = 0
    on_time: int = 0
    late: int = 0
    missed: int = 0

    @property
    def on_time_rate(self):
        return round(100 * self.on_time / self.total_planned, 2) if self.total_planned else None


@dataclass
class MachineHistory:
    machine_id: str
    machine_number: str
    machine_name: str
    years: list = field(default_factory=list)  # list[YearStats], oldest first
    chronically_missed: bool = False


def build_historical_variance(db: Session, machine_id: str | None = None) -> list[MachineHistory]:
    machines_q = db.query(Machine)
    if machine_id:
        machines_q = machines_q.filter(Machine.id == machine_id)
    machines = machines_q.all()

    histories = []
    for machine in machines:
        plans = (
            db.query(PMPlan)
            .filter(PMPlan.machine_id == machine.id, PMPlan.status != PMStatus.CANCELLED)
            .all()
        )
        if not plans:
            continue

        by_year = {}
        for plan in plans:
            stats = by_year.setdefault(plan.financial_year, YearStats(financial_year=plan.financial_year))
            stats.total_planned += 1

            actual = db.query(PMActual).filter(PMActual.pm_plan_id == plan.id).first()
            if actual and actual.actual_date:
                stats.completed += 1
                if actual.completion_class == CompletionClass.ON_TIME:
                    stats.on_time += 1
                elif actual.completion_class == CompletionClass.LATE:
                    stats.late += 1
            elif plan.status == PMStatus.MISSED:
                stats.missed += 1

        years_sorted = sorted(by_year.values(), key=lambda s: s.financial_year)
        poor_years = sum(
            1 for s in years_sorted
            if s.on_time_rate is not None and s.on_time_rate < CHRONIC_ON_TIME_THRESHOLD
        )

        histories.append(MachineHistory(
            machine_id=machine.id,
            machine_number=machine.machine_number,
            machine_name=machine.machine_name,
            years=years_sorted,
            chronically_missed=poor_years >= CHRONIC_MIN_YEARS,
        ))

    # Chronically-missed machines first, then by number of years of data
    # (more history = more confidence in the flag), so the report leads
    # with the machines most worth investigating.
    histories.sort(key=lambda h: (not h.chronically_missed, -len(h.years)))
    return histories
