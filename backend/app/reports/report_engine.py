"""
Computes the monthly PM performance report data (section 14 of the spec).
Pure calculation - rendering to PDF/Excel happens in report_render.py.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models.models import PMPlan, PMActual, Machine, Employee, PMStatus, CompletionClass, MachineResponsibility
from app.core.timeutils import today_local


@dataclass
class MonthlyReportData:
    month: str
    financial_year: str
    total_planned: int = 0
    completed: int = 0
    pending: int = 0
    overdue: int = 0
    on_time: int = 0
    late: int = 0
    missed: int = 0
    machine_rows: list = field(default_factory=list)
    location_rows: list = field(default_factory=list)
    employee_rows: list = field(default_factory=list)
    overdue_list: list = field(default_factory=list)

    @property
    def completion_rate(self):
        return round(100 * self.completed / self.total_planned, 2) if self.total_planned else 0.0

    @property
    def on_time_rate(self):
        return round(100 * self.on_time / self.total_planned, 2) if self.total_planned else 0.0

    @property
    def late_rate(self):
        return round(100 * self.late / self.total_planned, 2) if self.total_planned else 0.0

    @property
    def missed_rate(self):
        return round(100 * self.missed / self.total_planned, 2) if self.total_planned else 0.0


def build_monthly_report(db: Session, month: str, financial_year: str) -> MonthlyReportData:
    today = today_local()
    plans = db.query(PMPlan).filter(
        PMPlan.month == month, PMPlan.financial_year == financial_year
    ).all()

    report = MonthlyReportData(month=month, financial_year=financial_year, total_planned=len(plans))

    by_machine = {}
    by_location = {}
    by_employee = {}

    for plan in plans:
        machine = db.query(Machine).get(plan.machine_id)
        actual = db.query(PMActual).filter(PMActual.pm_plan_id == plan.id).first()
        location = machine.location or "Unspecified"

        m_key = machine.id
        by_machine.setdefault(m_key, {"machine": machine, "plan": 0, "actual": 0, "pending": 0, "overdue": 0})
        by_machine[m_key]["plan"] += 1

        by_location.setdefault(location, {"plan": 0, "actual": 0, "pending": 0})
        by_location[location]["plan"] += 1

        assigned = db.query(MachineResponsibility).filter(
            MachineResponsibility.machine_id == plan.machine_id,
            MachineResponsibility.responsibility_type == "PRIMARY",
        ).first()
        emp = db.query(Employee).get(assigned.employee_id) if assigned else None
        if emp:
            by_employee.setdefault(emp.id, {"employee": emp, "assigned": 0, "completed": 0, "pending": 0, "overdue": 0})
            by_employee[emp.id]["assigned"] += 1

        if actual and actual.actual_date:
            report.completed += 1
            by_machine[m_key]["actual"] += 1
            by_location[location]["actual"] += 1
            if emp:
                by_employee[emp.id]["completed"] += 1

            if actual.completion_class == CompletionClass.ON_TIME:
                report.on_time += 1
            elif actual.completion_class == CompletionClass.LATE:
                report.late += 1
        else:
            if plan.planned_date and plan.planned_date < today:
                report.overdue += 1
                by_machine[m_key]["overdue"] += 1
                by_location[location]["pending"] += 1
                if emp:
                    by_employee[emp.id]["overdue"] += 1
                report.overdue_list.append({
                    "machine_number": machine.machine_number,
                    "machine_name": machine.machine_name,
                    "planned_date": str(plan.planned_date),
                    "days_overdue": (today - plan.planned_date).days,
                    "assigned_to": emp.name if emp else "Unassigned",
                })
            else:
                report.pending += 1
                by_machine[m_key]["pending"] += 1
                by_location[location]["pending"] += 1
                if emp:
                    by_employee[emp.id]["pending"] += 1

    report.missed = 0  # reserved: a plan becomes "missed" via a separate end-of-month sweep, not computed here

    for data in by_machine.values():
        machine = data["machine"]
        perf = round(100 * data["actual"] / data["plan"], 2) if data["plan"] else 0
        report.machine_rows.append({
            "machine_number": machine.machine_number, "machine_name": machine.machine_name,
            "plan": data["plan"], "actual": data["actual"], "pending": data["pending"],
            "overdue": data["overdue"], "performance_pct": perf,
        })

    for location, data in by_location.items():
        perf = round(100 * data["actual"] / data["plan"], 2) if data["plan"] else 0
        report.location_rows.append({
            "location": location, "plan": data["plan"], "actual": data["actual"],
            "pending": data["pending"], "performance_pct": perf,
        })

    for data in by_employee.values():
        emp = data["employee"]
        report.employee_rows.append({
            "employee": emp.name, "assigned": data["assigned"], "completed": data["completed"],
            "pending": data["pending"], "overdue": data["overdue"],
        })

    return report
