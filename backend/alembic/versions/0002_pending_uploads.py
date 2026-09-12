"""add pending_uploads table (fixes client-controlled file path security issue)

Revision ID: 0002_pending_uploads
Revises: 0001_initial
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_pending_uploads"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pending_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_path", sa.String(1000), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("pending_uploads")
