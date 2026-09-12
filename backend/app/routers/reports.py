from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import require_roles
from app.core.audit import record_audit
from app.models.models import Role, Employee
from app.reports.report_engine import build_monthly_report
from app.reports.report_render import render_pdf, render_excel
from app.reports.data_quality import build_data_quality_report
from app.reports.historical_variance import build_historical_variance

router = APIRouter(prefix="/api/reports", tags=["reports"])

ViewRoles = require_roles(Role.ADMIN, Role.MANAGER, Role.SUPERVISOR, Role.VIEWER)


@router.get("/monthly")
def get_monthly_report(month: str, financial_year: str, db: Session = Depends(get_db), _user=Depends(ViewRoles)):
    report = build_monthly_report(db, month, financial_year)
    return {
        "month": report.month, "financial_year": report.financial_year,
        "total_planned": report.total_planned, "completed": report.completed,
        "pending": report.pending, "overdue": report.overdue,
        "completion_rate": report.completion_rate, "on_time_rate": report.on_time_rate,
        "late_rate": report.late_rate,
        "machine_rows": report.machine_rows, "location_rows": report.location_rows,
        "employee_rows": report.employee_rows, "overdue_list": report.overdue_list,
    }


@router.get("/historical-variance")
def get_historical_variance(
    machine_id: str | None = None, db: Session = Depends(get_db), _user=Depends(ViewRoles),
):
    """
    Per-machine, per-financial-year Plan-vs-Actual stats across every year
    that's been imported (accuracy-improvements item 3) - shows historical
    on-time rate per machine rather than just the current year, and flags
    machines whose on-time rate has been chronically poor across years.
    Pass machine_id to drill into a single machine's year-by-year history.
    """
    histories = build_historical_variance(db, machine_id=machine_id)
    return {
        "machines": [
            {
                "machine_id": h.machine_id,
                "machine_number": h.machine_number,
                "machine_name": h.machine_name,
                "chronically_missed": h.chronically_missed,
                "years": [
                    {
                        "financial_year": y.financial_year,
                        "total_planned": y.total_planned,
                        "completed": y.completed,
                        "on_time": y.on_time,
                        "late": y.late,
                        "missed": y.missed,
                        "on_time_rate": y.on_time_rate,
                    }
                    for y in h.years
                ],
            }
            for h in histories
        ]
    }


@router.get("/data-quality")
def get_data_quality_report(financial_year: str, db: Session = Depends(get_db), _user=Depends(ViewRoles)):
    """
    One-click 'audit the imported data' view (accuracy-improvements item 5):
    machines missing a responsible person, machines with a 2+ consecutive
    month plan gap, machines with no location, PMPlan rows the importer
    flagged for human review, and machines still pending near-duplicate
    review - all things that quietly break automation without erroring out.
    """
    report = build_data_quality_report(db, financial_year)
    return {
        "financial_year": report.financial_year,
        "total_issues": report.total_issues,
        "machines_missing_responsible": report.machines_missing_responsible,
        "machines_with_plan_gaps": report.machines_with_plan_gaps,
        "machines_missing_location": report.machines_missing_location,
        "plans_needing_review": report.plans_needing_review,
        "potential_duplicate_machines": report.potential_duplicate_machines,
    }


@router.post("/monthly/generate")
def generate_monthly_report(
    month: str, financial_year: str, format: str = "pdf",
    db: Session = Depends(get_db),
    user: Employee = Depends(require_roles(Role.ADMIN, Role.MANAGER)),
):
    report = build_monthly_report(db, month, financial_year)
    path = render_pdf(report) if format == "pdf" else render_excel(report)

    record_audit(db, action="REPORT_GENERATED", entity_type="MonthlyReport",
                 entity_id=f"{month}-{financial_year}", actor_id=user.id,
                 new_value={"format": format, "completion_rate": report.completion_rate})

    return FileResponse(path, filename=f"pm_report_{month}_{financial_year}.{ 'pdf' if format=='pdf' else 'xlsx' }")
