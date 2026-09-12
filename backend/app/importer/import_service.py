"""
Bridges the pure-parsing layer (excel_importer.py) and the database.

Two modes:
  - preview=True  -> parses and diffs against existing DB, returns a summary,
                      writes NOTHING.
  - preview=False -> same diff, then commits Machine / PMPlan rows inside one
                      transaction, records an ImportBatch, and returns the summary.

Duplicate prevention: PMPlan has a unique constraint on
(machine_id, month, financial_year, source_sheet), so re-importing the same
month/sheet updates the existing row (if changed) instead of creating a
duplicate.
"""

from dataclasses import asdict
from typing import Optional

from sqlalchemy.orm import Session

from app.importer.excel_importer import (
    load_workbook_from_bytes, parse_pm_sheet, compute_file_hash, ImportResult,
    normalize_for_dedup, validate_financial_year,
)
from app.models.models import Machine, PMPlan, ImportBatch, PlanSourceType, PMStatus
from app.core.settings_service import get_setting


def run_import(
    db: Session,
    file_bytes: bytes,
    original_filename: str,
    sheet_name: str,
    financial_year: str,
    uploaded_by: Optional[str] = None,
    preview: bool = True,
) -> dict:
    # Fail fast and clearly (Medium: "Excel import needs stronger
    # validation around commit") - previously a malformed financial_year
    # only surfaced as an unhandled ValueError deep inside date resolution,
    # after the workbook had already been opened and parsed.
    try:
        validate_financial_year(financial_year)
    except ValueError as e:
        return {"errors": [str(e)], "warnings": [], "sheet": sheet_name, "financial_year": financial_year}

    wb = load_workbook_from_bytes(file_bytes)
    if sheet_name not in wb.sheetnames:
        return {"errors": [f"Sheet '{sheet_name}' not found in workbook."]}

    ws = wb[sheet_name]
    week_band_size_days = get_setting(db, "week_band_size_days")
    week_start_offset_days = get_setting(db, "week_start_offset_days")
    parsed: ImportResult = parse_pm_sheet(
        ws, sheet_name, financial_year,
        week_band_size_days=week_band_size_days,
        week_start_offset_days=week_start_offset_days,
    )

    summary = {
        "sheet": sheet_name,
        "financial_year": financial_year,
        "machines_seen": len(parsed.rows),
        "machines_created": 0,
        "machines_updated": 0,
        "pm_plans_created": 0,
        "pm_plans_updated": 0,
        "pm_plans_removed": 0,
        "duplicates_skipped": 0,
        "warnings": parsed.warnings,
        "errors": parsed.errors,
        "preview_rows": [],
        "removed_rows": [],
        "needs_review_count": 0,
        "potential_duplicates": [],
    }

    # Duplicate machine numbers *within this one sheet* (Medium: "Excel
    # import needs stronger validation around commit" - a workbook listing
    # the same machine number+location twice is almost always a copy-paste
    # mistake, and silently processing both rows means the second row's
    # values win with no indication anything was overwritten).
    seen_in_sheet = {}
    for row in parsed.rows:
        dup_key = (row.machine_number, row.location)
        if dup_key in seen_in_sheet:
            summary["warnings"].append(
                f"Machine '{row.machine_number}' ({row.location or 'no location'}) appears more than once "
                f"in this sheet - only the last occurrence will be kept."
            )
        seen_in_sheet[dup_key] = row

    # Near-duplicate check: normalize every EXISTING machine's (number, name)
    # the same way as incoming rows (letters/digits only, lowercased) so two
    # records that differ solely by spacing/punctuation collapse to the same
    # key. Machines whose alphanumeric content actually differs are never
    # matched here - that's a different physical machine, not a typo.
    existing_machines = db.query(Machine).all()
    existing_by_dedup_key = {}
    for m in existing_machines:
        existing_by_dedup_key.setdefault(normalize_for_dedup(m.machine_number, m.machine_name), []).append(m)

    # Everything below runs identically in preview and commit mode (the only
    # difference is whether writes/deletes are actually flushed to the DB) so
    # the "preview" the user sees is a true dry-run of the exact same diff,
    # not an approximation of it.
    seen_plan_keys = set()  # (machine_number, location, month) present in the new file

    # Create the ImportBatch up front (not at the end) and flush to get its
    # id so every PMPlan created/touched below can carry a real
    # import_batch_id (High Priority: "Import batch isn't properly linked
    # to PM plans" - previously the batch row was created after all the
    # PMPlan writes, so traceability back to "which upload produced this
    # row" was silently lost). Only meaningful in commit mode; a preview
    # never writes anything and is rolled back by the caller.
    batch = None
    if not preview:
        batch = ImportBatch(
            original_filename=original_filename,
            file_hash=compute_file_hash(file_bytes),
            uploaded_by=uploaded_by,
            status="IN_PROGRESS",
        )
        db.add(batch)
        db.flush()  # get batch.id before any PMPlan rows are created

    for row in parsed.rows:
        machine = db.query(Machine).filter(
            Machine.machine_number == row.machine_number,
            Machine.location == row.location,
        ).first()

        machine_is_new = machine is None

        # Near-duplicate detection: does another machine already in the DB
        # collapse to the same dedup key (same letters/digits, different
        # punctuation/spacing only)? Only relevant/reported for genuinely
        # different DB rows, not the exact machine we just matched above.
        dup_candidates = [
            m for m in existing_by_dedup_key.get(row.dedup_key, [])
            if machine is None or m.id != machine.id
        ]
        if dup_candidates:
            summary["potential_duplicates"].append({
                "machine_number": row.machine_number,
                "machine_name": row.machine_name,
                "matches": [
                    {"id": m.id, "machine_number": m.machine_number,
                     "machine_name": m.machine_name, "location": m.location}
                    for m in dup_candidates
                ],
            })

        if machine_is_new:
            summary["machines_created"] += 1
            if not preview:
                machine = Machine(
                    machine_number=row.machine_number,
                    machine_name=row.machine_name,
                    manufacturer=row.manufacturer,
                    specification=row.specification,
                    location=row.location,
                    remarks=row.remarks,
                    critical=row.critical,
                )
                if dup_candidates:
                    machine.potential_duplicate_of_id = dup_candidates[0].id
                    machine.duplicate_review_status = "PENDING"
                db.add(machine)
                db.flush()  # get machine.id
                existing_by_dedup_key.setdefault(row.dedup_key, []).append(machine)
        else:
            summary["machines_updated"] += 1
            if not preview:
                machine.machine_name = row.machine_name or machine.machine_name
                machine.manufacturer = row.manufacturer or machine.manufacturer
                machine.specification = row.specification or machine.specification
                machine.remarks = row.remarks or machine.remarks

        row_preview = {
            "machine_number": row.machine_number, "machine_name": row.machine_name, "months": [],
            "needs_review": row.needs_review, "review_reasons": row.review_reasons,
        }
        if row.needs_review:
            summary["needs_review_count"] += 1

        for plan in row.plans:
            seen_plan_keys.add((row.machine_number, row.location, plan.month))

            existing_plan = None
            if machine is not None and not machine_is_new:
                existing_plan = db.query(PMPlan).filter(
                    PMPlan.machine_id == machine.id,
                    PMPlan.month == plan.month,
                    PMPlan.financial_year == financial_year,
                    PMPlan.source_sheet == sheet_name,
                ).first()

            if existing_plan:
                changed = (
                    existing_plan.planned_date != plan.planned_date
                    or existing_plan.planned_week != plan.planned_week
                    or existing_plan.plan_source_raw_value != plan.plan_source_raw_value
                )
                diff_action = "unchanged"
                if changed:
                    diff_action = "updated"
                    summary["pm_plans_updated"] += 1
                    if not preview:
                        existing_plan.planned_date = plan.planned_date
                        existing_plan.planned_week = plan.planned_week
                        existing_plan.plan_source_raw_value = plan.plan_source_raw_value
                        existing_plan.low_confidence_actual = plan.low_confidence_actual
                        existing_plan.needs_review = plan.needs_review
                        existing_plan.review_reasons = plan.review_reasons
                        existing_plan.import_batch_id = batch.id
                else:
                    summary["duplicates_skipped"] += 1
            else:
                diff_action = "added"
                summary["pm_plans_created"] += 1
                if not preview and machine is not None:
                    db.add(PMPlan(
                        machine_id=machine.id,
                        planned_date=plan.planned_date,
                        planned_week=plan.planned_week,
                        plan_source_type=PlanSourceType(plan.plan_source_type),
                        plan_source_raw_value=plan.plan_source_raw_value,
                        month=plan.month,
                        financial_year=financial_year,
                        status=PMStatus.PLANNED,
                        source_file=original_filename,
                        source_sheet=sheet_name,
                        source_cell=plan.source_cell_plan,
                        low_confidence_actual=plan.low_confidence_actual,
                        needs_review=plan.needs_review,
                        review_reasons=plan.review_reasons,
                        import_batch_id=batch.id,
                    ))

            row_preview["months"].append({
                "month": plan.month,
                "planned_date": str(plan.planned_date) if plan.planned_date else None,
                "planned_week": plan.planned_week,
                "source_type": plan.plan_source_type,
                "low_confidence_actual": plan.low_confidence_actual,
                "needs_review": plan.needs_review,
                "review_reasons": plan.review_reasons,
                "diff": diff_action,
            })

        summary["preview_rows"].append(row_preview)

    # --- removed detection -------------------------------------------------
    # Any PMPlan already in the DB for this exact sheet/FY whose
    # (machine_number, location, month) is no longer present in the freshly
    # parsed file is a candidate "removed" row — the maintenance team deleted
    # or renamed that row in Excel. We never silently hard-delete completed
    # work: a plan with a recorded PMActual is left alone and just flagged;
    # an incomplete plan is cancelled (not deleted) in commit mode so the
    # history/audit trail is preserved.
    existing_for_sheet = (
        db.query(PMPlan)
        .join(Machine, PMPlan.machine_id == Machine.id)
        .filter(PMPlan.financial_year == financial_year, PMPlan.source_sheet == sheet_name)
        .all()
    )
    for existing_plan in existing_for_sheet:
        machine = db.query(Machine).get(existing_plan.machine_id)
        key = (machine.machine_number, machine.location, existing_plan.month) if machine else None
        if key and key not in seen_plan_keys and existing_plan.status != PMStatus.CANCELLED:
            has_actual = existing_plan.actual is not None and existing_plan.actual.actual_date is not None
            summary["pm_plans_removed"] += 1
            summary["removed_rows"].append({
                "machine_number": machine.machine_number,
                "machine_name": machine.machine_name,
                "month": existing_plan.month,
                "planned_date": str(existing_plan.planned_date) if existing_plan.planned_date else None,
                "action": "flagged (has completed actual, not touched)" if has_actual else (
                    "cancelled" if not preview else "will be cancelled"
                ),
            })
            if not preview and not has_actual:
                existing_plan.status = PMStatus.CANCELLED

    if not preview:
        # `batch` was created and flushed at the top of this function so its
        # id was available to stamp onto every PMPlan row above - fill in
        # the summary counts now that they're known, rather than creating a
        # second, disconnected ImportBatch row here.
        batch.machines_created = summary["machines_created"]
        batch.machines_updated = summary["machines_updated"]
        batch.pm_plans_created = summary["pm_plans_created"]
        batch.pm_plans_updated = summary["pm_plans_updated"]
        batch.pm_plans_removed = summary["pm_plans_removed"]
        batch.duplicates_skipped = summary["duplicates_skipped"]
        batch.warnings = summary["warnings"] + (
            [f"{summary['needs_review_count']} row(s) flagged for human review."]
            if summary["needs_review_count"] else []
        ) + (
            [f"{len(summary['potential_duplicates'])} potential near-duplicate machine(s) found."]
            if summary["potential_duplicates"] else []
        )
        batch.errors = summary["errors"]
        batch.status = "COMPLETED"
        db.commit()
        summary["import_batch_id"] = batch.id

    return summary
