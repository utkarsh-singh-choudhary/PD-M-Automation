"""Enforce unique employee email (case-normalized) and link PMPlan to its
ImportBatch, closing two gaps from the production security/audit review:

  - Employee.email had no uniqueness constraint even though login looks
    users up by email, which made authentication ambiguous whenever two
    rows shared an address.
  - PMPlan.import_batch_id existed on the model but was never actually
    populated by the importer, breaking the Import Batch -> PMPlan
    traceability the audit trail depends on.

Before adding the unique index, existing duplicate/mixed-case emails are
normalized to lowercase and, if a true duplicate remains, all but the
oldest row are nulled out rather than the migration failing outright -
an admin can then re-invite/re-set those accounts explicitly.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_employee_email_unique"
down_revision = "0004_completed_on_behalf"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. Normalize case so "Abc@x.com" and "abc@x.com" collapse together.
    conn.execute(sa.text(
        "UPDATE employees SET email = lower(email) WHERE email IS NOT NULL"
    ))

    # 2. Any remaining duplicates (same lowercase email on >1 row): keep the
    #    oldest (by created_at) usable, null out the rest so the unique
    #    index below can be created. This is a data-safety fallback, not
    #    the expected path in a normally-run system.
    conn.execute(sa.text(
        """
        WITH ranked AS (
            SELECT id, email,
                   ROW_NUMBER() OVER (
                       PARTITION BY email ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM employees
            WHERE email IS NOT NULL
        )
        UPDATE employees
        SET email = NULL
        FROM ranked
        WHERE employees.id = ranked.id AND ranked.rn > 1
        """
    ))

    op.create_unique_constraint("uq_employee_email", "employees", ["email"])

    # No PMPlan schema change needed for the ImportBatch linkage fix -
    # pm_plans.import_batch_id already existed; the importer just wasn't
    # populating it (see app/importer/import_service.py). Existing rows
    # imported before this fix will simply keep a NULL import_batch_id,
    # same as before.


def downgrade():
    op.drop_constraint("uq_employee_email", "employees", type_="unique")
