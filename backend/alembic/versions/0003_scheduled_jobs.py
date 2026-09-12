"""add scheduled_jobs table (fixes monthly report double-send risk)

Revision ID: 0003_scheduled_jobs
Revises: 0002_pending_uploads
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_scheduled_jobs"
down_revision = "0002_pending_uploads"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("job_type", "period", name="uq_scheduled_job_type_period"),
    )


def downgrade():
    op.drop_table("scheduled_jobs")
