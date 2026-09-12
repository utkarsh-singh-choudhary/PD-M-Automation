#!/usr/bin/env bash
# Restore a pg_dump custom-format backup created by scripts/backup.sh.
#
# DESTRUCTIVE: drops and recreates the target database before restoring.
# Always restore into a *scratch* database first to verify the dump is
# good, before ever pointing this at production - see the two-step
# workflow below.
#
# Usage:
#   ./scripts/restore.sh /mnt/backups/pm_system/pm_system_20260911_020000.dump [target_db_name]
#
# Verify-first workflow (recommended):
#   ./scripts/restore.sh backups/pm_system_20260911_020000.dump pm_system_restore_test
#   # inspect pm_system_restore_test, confirm row counts / spot-check data
#   ./scripts/restore.sh backups/pm_system_20260911_020000.dump pm_system   # only once verified
set -euo pipefail

DUMP_FILE="${1:?Usage: restore.sh <dump_file> [target_db_name]}"
TARGET_DB="${2:-pm_system}"
CONTAINER_NAME="${CONTAINER_NAME:-pm-system-db-1}"
DB_USER="${POSTGRES_USER:-pm_user}"

if [ ! -s "$DUMP_FILE" ]; then
    echo "[restore] ERROR: dump file '$DUMP_FILE' is missing or empty" >&2
    exit 1
fi

echo "[restore] this will DROP and recreate database '${TARGET_DB}' in container '${CONTAINER_NAME}'."
read -r -p "Type the database name to confirm: " confirm
if [ "$confirm" != "$TARGET_DB" ]; then
    echo "[restore] confirmation did not match - aborting." >&2
    exit 1
fi

docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"${TARGET_DB}\";"
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE \"${TARGET_DB}\" OWNER \"${DB_USER}\";"

basefile=$(basename "$DUMP_FILE")
docker cp "$DUMP_FILE" "$CONTAINER_NAME:/tmp/$basefile"
docker exec "$CONTAINER_NAME" pg_restore -U "$DB_USER" -d "$TARGET_DB" --no-owner --no-privileges "/tmp/$basefile"
docker exec "$CONTAINER_NAME" rm -f "/tmp/$basefile"

echo "[restore] done. Restored '${DUMP_FILE}' into database '${TARGET_DB}'."
echo "[restore] if this was the verify-test target, spot-check it before restoring into production."
