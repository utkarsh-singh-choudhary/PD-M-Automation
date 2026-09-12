#!/usr/bin/env bash
# Nightly Postgres backup for the PM system.
#
# Runs `pg_dump` in custom format (-Fc: compressed, supports selective
# restore and pg_restore's parallel jobs, unlike a plain .sql dump) against
# the `db` container, timestamps the file, and prunes anything older than
# RETENTION_DAYS. Intended to run via a host cron / systemd timer, NOT
# inside docker-compose.yml itself - backups should not depend on the same
# machine/volume they're protecting against.
#
# Usage:
#   BACKUP_DIR=/mnt/backups/pm_system ./scripts/backup.sh
#
# Suggested cron (2am IST daily, before the 8am reminder job and well clear
# of the 1st-of-month report job):
#   0 2 * * * BACKUP_DIR=/mnt/backups/pm_system /path/to/pm-system/scripts/backup.sh >> /var/log/pm_backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
CONTAINER_NAME="${CONTAINER_NAME:-pm-system-db-1}"  # docker compose default project_service_index naming
DB_USER="${POSTGRES_USER:-pm_user}"
DB_NAME="${POSTGRES_DB:-pm_system}"

mkdir -p "$BACKUP_DIR"
timestamp=$(date +%Y%m%d_%H%M%S)
outfile="$BACKUP_DIR/pm_system_${timestamp}.dump"

echo "[backup] dumping ${DB_NAME} from container ${CONTAINER_NAME} -> ${outfile}"
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc -f "/tmp/$(basename "$outfile")"
docker cp "$CONTAINER_NAME:/tmp/$(basename "$outfile")" "$outfile"
docker exec "$CONTAINER_NAME" rm -f "/tmp/$(basename "$outfile")"

# Sanity check: a 0-byte or missing dump means the backup silently failed -
# never let that pass as "success".
if [ ! -s "$outfile" ]; then
    echo "[backup] ERROR: dump file is missing or empty - aborting without pruning old backups" >&2
    exit 1
fi
echo "[backup] OK: $(du -h "$outfile" | cut -f1)"

echo "[backup] pruning dumps older than ${RETENTION_DAYS} days in ${BACKUP_DIR}"
find "$BACKUP_DIR" -name 'pm_system_*.dump' -mtime "+${RETENTION_DAYS}" -print -delete
