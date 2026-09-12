"""
"Audit the imported data" view (accuracy-improvements item 5).

Surfaces things that quietly break automation without ever raising an
error - a machine with nobody responsible never gets a reminder sent to
anyone; a machine with no plan for months just silently never shows up as
overdue. None of these are import-time errors, so they need their own
sweep over the current DB state rather than living in the importer.

Pure read/compute module - no writes, safe to call anytime.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models.models import Machine, PMPlan, MachineResponsibility

# "No plan for N+ consecutive months" threshold (business-tunable constant,
# not wired to AppSetting yet - bump here if 2 turns out too noisy/quiet).
CONSECUTIVE_GAP_MONTHS = 2

MONTH_ORDER = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March",
]


@dataclass
class DataQualityReport:
    financial_year: str
    machines_missing_responsible: list = field(default_factory=list)
    machines_with_plan_gaps: list = field(default_factory=list)
    machines_missing_location: list = field(default_factory=list)
    plans_needing_review: list = field(default_factory=list)
    potential_duplicate_machines: list = field(default_factory=list)

    @property
    def total_issues(self):
        return (
            len(self.machines_missing_responsible)
            + len(self.machines_with_plan_gaps)
            + len(self.machines_missing_location)
            + len(self.plans_needing_review)
            + len(self.potential_duplicate_machines)
        )


def _consecutive_gaps(months_present: set) -> list:
    """Returns list of (start_month, length) for runs of >=CONSECUTIVE_GAP_MONTHS
    consecutive months (in FY order) that have no plan at all."""
    gaps = []
    run_start, run_len = None, 0
    for month in MONTH_ORDER:
        if month not in months_present:
            if run_start is None:
                run_start = month
            run_len += 1
        else:
            if run_len >= CONSECUTIVE_GAP_MONTHS:
                gaps.append((run_start, run_len))
            run_start, run_len = None, 0
    if run_len >= CONSECUTIVE_GAP_MONTHS:
        gaps.append((run_start, run_len))
    return gaps


def build_data_quality_report(db: Session, financial_year: str) -> DataQualityReport:
    report = DataQualityReport(financial_year=financial_year)

    machines = db.query(Machine).filter(Machine.active == True).all()  # noqa: E712
    responsible_machine_ids = {
        r.machine_id for r in db.query(MachineResponsibility).all()
    }

    plans = (
        db.query(PMPlan)
        .filter(PMPlan.financial_year == financial_year)
        .all()
    )
    months_by_machine = {}
    for p in plans:
        months_by_machine.setdefault(p.machine_id, set()).add(p.month)
        if p.needs_review:
            report.plans_needing_review.append({
                "pm_plan_id": p.id, "machine_id": p.machine_id,
                "month": p.month, "reasons": p.review_reasons,
            })

    for m in machines:
        if m.id not in responsible_machine_ids:
            report.machines_missing_responsible.append(
                {"machine_id": m.id, "machine_number": m.machine_number, "machine_name": m.machine_name}
            )
        if not m.location:
            report.machines_missing_location.append(
                {"machine_id": m.id, "machine_number": m.machine_number, "machine_name": m.machine_name}
            )
        if m.duplicate_review_status == "PENDING":
            report.potential_duplicate_machines.append({
                "machine_id": m.id, "machine_number": m.machine_number,
                "machine_name": m.machine_name,
                "potential_duplicate_of_id": m.potential_duplicate_of_id,
            })

        gaps = _consecutive_gaps(months_by_machine.get(m.id, set()))
        for start_month, length in gaps:
            report.machines_with_plan_gaps.append({
                "machine_id": m.id, "machine_number": m.machine_number,
                "machine_name": m.machine_name,
                "gap_start_month": start_month, "gap_length_months": length,
            })

    return report
