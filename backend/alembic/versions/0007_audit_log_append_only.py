"""
Make audit_logs append-only at the database level (Medium: "Audit log
should be protected from normal application modification"). Previously
this was purely a convention - any code path with a DB session could
UPDATE or DELETE an audit row like any other table. A trigger enforces it
regardless of which application code (or future bug, or direct psql
session under the app's own role) touches the table.

This intentionally does NOT try to restrict a superuser/db-owner - that's
a role/grant exercise for your hosting setup (Render's default DB user is
typically the owner and can't be fully locked out of its own tables
without a second, restricted app role). The trigger's real job is to stop
the *application*, running with its normal credentials, from ever calling
UPDATE/DELETE on this table through an ORM bug or a future admin
"cleanup" endpoint that shouldn't exist.
"""
from alembic import op

revision = "0007_audit_log_append_only"
down_revision = "0006_refresh_tokens"
branch_labels = None
depends_on = None

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""

_TRIGGER = """
CREATE TRIGGER audit_logs_append_only
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
"""


def upgrade():
    op.execute(_TRIGGER_FN)
    op.execute(_TRIGGER)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation();")
