"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-11

Hand-written to match app/models/models.py as of Phase 4 (RBAC + reports +
admin settings). Since this is the first production deploy, this single
migration creates the full schema in one shot rather than replaying dev
history. Future schema changes should be added as new revisions via
`alembic revision --autogenerate -m "..."` against a running DB — never
edit this file after it has been applied anywhere.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# Enum type names must match app.models.models exactly (SQLAlchemy's
# SAEnum(SomeEnum) derives the Postgres type name from the class name
# lower-cased, unless name= is given — these do not use name=, so SQLAlchemy
# uses the enum class's __name__.lower() by default via native_enum).
pm_status = postgresql.ENUM(
    "PLANNED", "REMINDER_SENT", "DUE", "IN_PROGRESS", "COMPLETED",
    "OVERDUE", "MISSED", "CANCELLED", "PENDING_SUPERVISOR_CONFIRMATION", name="pmstatus",
)
plan_source_type = postgresql.ENUM("EXACT_DATE", "WEEK_CODE", "DAY_OF_MONTH", name="plansourcetype")
completion_class = postgresql.ENUM("EARLY", "ON_TIME", "LATE", name="completionclass")
notification_type = postgresql.ENUM(
    "UPCOMING_REMINDER", "DUE_REMINDER", "OVERDUE_REMINDER", "ESCALATION", "MONTHLY_REPORT",
    name="notificationtype",
)
notification_channel = postgresql.ENUM("EMAIL", "WHATSAPP", "SMS", name="notificationchannel")
delivery_status = postgresql.ENUM("PENDING", "SENT", "FAILED", "RETRYING", name="deliverystatus")
role_enum = postgresql.ENUM("ADMIN", "MANAGER", "SUPERVISOR", "TECHNICIAN", "VIEWER", name="role")


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (pm_status, plan_source_type, completion_class,
                       notification_type, notification_channel, delivery_status, role_enum):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "employees",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employee_code", sa.String(50), unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("department", sa.String(150)),
        sa.Column("designation", sa.String(150)),
        sa.Column("role", role_enum, server_default="TECHNICIAN"),
        sa.Column("notification_email_enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("notification_whatsapp_enabled", sa.Boolean(), server_default=sa.false()),
        sa.Column("active", sa.Boolean(), server_default=sa.true()),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "checklist_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("active", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "checklist_template_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("template_id", sa.String(), sa.ForeignKey("checklist_templates.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.true()),
    )

    op.create_table(
        "machines",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("machine_number", sa.String(100), nullable=False),
        sa.Column("machine_name", sa.String(255), nullable=False),
        sa.Column("manufacturer", sa.String(255)),
        sa.Column("specification", sa.String(500)),
        sa.Column("location", sa.String(255)),
        sa.Column("remarks", sa.Text()),
        sa.Column("critical", sa.Boolean(), server_default=sa.false()),
        sa.Column("active", sa.Boolean(), server_default=sa.true()),
        sa.Column("potential_duplicate_of_id", sa.String(), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("duplicate_review_status", sa.String(20), nullable=True),
        sa.Column("checklist_template_id", sa.String(), sa.ForeignKey("checklist_templates.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("machine_number", "location", name="uq_machine_number_location"),
    )
    op.create_index("ix_machines_machine_number", "machines", ["machine_number"])

    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_hash", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("uploaded_by", sa.String(), sa.ForeignKey("employees.id")),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("machines_created", sa.Integer(), server_default="0"),
        sa.Column("machines_updated", sa.Integer(), server_default="0"),
        sa.Column("pm_plans_created", sa.Integer(), server_default="0"),
        sa.Column("pm_plans_updated", sa.Integer(), server_default="0"),
        sa.Column("pm_plans_removed", sa.Integer(), server_default="0"),
        sa.Column("duplicates_skipped", sa.Integer(), server_default="0"),
        sa.Column("warnings", postgresql.JSONB(), server_default="[]"),
        sa.Column("errors", postgresql.JSONB(), server_default="[]"),
        sa.Column("status", sa.String(30), server_default="COMPLETED"),
    )

    op.create_table(
        "machine_responsibilities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("machine_id", sa.String(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("employee_id", sa.String(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("responsibility_type", sa.String(50), server_default="PRIMARY"),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
    )

    op.create_table(
        "pm_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("machine_id", sa.String(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("planned_date", sa.Date()),
        sa.Column("planned_week", sa.String(5)),
        sa.Column("plan_source_type", plan_source_type, nullable=False),
        sa.Column("plan_source_raw_value", sa.String(50)),
        sa.Column("month", sa.String(20), nullable=False),
        sa.Column("financial_year", sa.String(10), nullable=False),
        sa.Column("status", pm_status, server_default="PLANNED"),
        sa.Column("assigned_to", sa.String(), sa.ForeignKey("employees.id")),
        sa.Column("source_file", sa.String(500)),
        sa.Column("source_sheet", sa.String(150)),
        sa.Column("source_cell", sa.String(20)),
        sa.Column("import_batch_id", sa.String(), sa.ForeignKey("import_batches.id")),
        sa.Column("imported_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("low_confidence_actual", sa.Boolean(), server_default=sa.false()),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.false()),
        sa.Column("review_reasons", postgresql.JSONB(), server_default="[]"),
        sa.Column("completed_by_technician_id", sa.String(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("confirmed_by_supervisor_id", sa.String(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("machine_id", "month", "financial_year", "source_sheet",
                             name="uq_pmplan_machine_month_fy_sheet"),
    )
    op.create_index("ix_pmplan_machine_id", "pm_plans", ["machine_id"])
    op.create_index("ix_pmplan_planned_date", "pm_plans", ["planned_date"])
    op.create_index("ix_pmplan_status", "pm_plans", ["status"])
    op.create_index("ix_pmplan_status_date", "pm_plans", ["status", "planned_date"])
    op.create_index("ix_pmplan_needs_review", "pm_plans", ["needs_review"])

    op.create_table(
        "pm_actuals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pm_plan_id", sa.String(), sa.ForeignKey("pm_plans.id"), nullable=False, unique=True),
        sa.Column("actual_date", sa.Date()),
        sa.Column("completed_by", sa.String(), sa.ForeignKey("employees.id")),
        sa.Column("remarks", sa.Text()),
        sa.Column("delay_reason", sa.Text()),
        sa.Column("downtime_minutes", sa.Integer()),
        sa.Column("delay_days", sa.Integer()),
        sa.Column("completion_class", completion_class),
        sa.Column("attachment_path", sa.String(500)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "pm_checklist_responses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pm_actual_id", sa.String(), sa.ForeignKey("pm_actuals.id"), nullable=False),
        sa.Column("checklist_template_item_id", sa.String(), sa.ForeignKey("checklist_template_items.id"), nullable=False),
        sa.Column("checked", sa.Boolean(), server_default=sa.false()),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("pm_actual_id", "checklist_template_item_id", name="uq_checklist_response_actual_item"),
    )
    op.create_index("ix_pmchecklistresponse_actual", "pm_checklist_responses", ["pm_actual_id"])

    op.create_table(
        "breakdown_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("machine_id", sa.String(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("breakdown_at", sa.DateTime(), nullable=False),
        sa.Column("resumed_at", sa.DateTime(), nullable=True),
        sa.Column("reported_by", sa.String(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("repaired_by", sa.String(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("cause", sa.Text()),
        sa.Column("action_taken", sa.Text()),
        sa.Column("resulted_in_scrap_or_replace", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_breakdownevent_machine", "breakdown_events", ["machine_id"])

    op.create_table(
        "notification_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pm_plan_id", sa.String(), sa.ForeignKey("pm_plans.id"), nullable=False),
        sa.Column("recipient_id", sa.String(), sa.ForeignKey("employees.id")),
        sa.Column("notification_type", notification_type, nullable=False),
        sa.Column("channel", notification_channel, server_default="EMAIL"),
        sa.Column("provider", sa.String(50)),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("delivery_status", delivery_status, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_idempotency"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("employees.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100)),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("old_value", postgresql.JSONB()),
        sa.Column("new_value", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_auditlog_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("updated_by", sa.String(), sa.ForeignKey("employees.id")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_auditlog_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("notification_logs")
    op.drop_index("ix_breakdownevent_machine", table_name="breakdown_events")
    op.drop_table("breakdown_events")
    op.drop_index("ix_pmchecklistresponse_actual", table_name="pm_checklist_responses")
    op.drop_table("pm_checklist_responses")
    op.drop_table("pm_actuals")
    op.drop_index("ix_pmplan_needs_review", table_name="pm_plans")
    op.drop_index("ix_pmplan_status_date", table_name="pm_plans")
    op.drop_index("ix_pmplan_status", table_name="pm_plans")
    op.drop_index("ix_pmplan_planned_date", table_name="pm_plans")
    op.drop_index("ix_pmplan_machine_id", table_name="pm_plans")
    op.drop_table("pm_plans")
    op.drop_table("machine_responsibilities")
    op.drop_table("import_batches")
    op.drop_index("ix_machines_machine_number", table_name="machines")
    op.drop_table("machines")
    op.drop_table("checklist_template_items")
    op.drop_table("checklist_templates")
    op.drop_table("employees")

    bind = op.get_bind()
    for enum_type in (role_enum, delivery_status, notification_channel,
                       notification_type, completion_class, plan_source_type, pm_status):
        enum_type.drop(bind, checkfirst=True)
