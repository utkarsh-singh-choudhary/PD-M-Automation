"""Add refresh_tokens table for revocable sessions (JWT/session hardening).

See app/models/models.py:RefreshToken for the rationale - short-lived
access tokens plus a server-side, revocable refresh token, instead of a
single long-lived unrevocable bearer JWT.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_refresh_tokens"
down_revision = "0005_employee_email_unique"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("issued_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("ip_address", sa.String(64)),
    )
    op.create_index("ix_refresh_tokens_employee_id", "refresh_tokens", ["employee_id"])
    op.create_unique_constraint("uq_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])


def downgrade():
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_constraint("uq_refresh_tokens_token_hash", "refresh_tokens", type_="unique")
    op.drop_index("ix_refresh_tokens_employee_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
