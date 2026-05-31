#!/usr/bin/env bash
# Nightly data backup for the self-hosted SWE-Jobs Postgres container.
#
# Produces a gzipped, data-only dump that restores into a fresh container (which
# rebuilds the schema from supabase/migrations + docker/postgres/000_roles.sql).
#
# Usage:  ./scripts/backup_db.sh [BACKUP_DIR]            (default: ./backups)
# Cron:   0 3 * * * cd ~/SWE-Jobs && ./scripts/backup_db.sh >> backups/backup.log 2>&1
#
# Restore: docker compose down -v && docker compose up -d --build db
#          zcat backups/swejobs_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U postgres -d postgres
set -euo pipefail

BACKUP_DIR="${1:-backups}"
KEEP="${KEEP:-14}"                 # number of backups to retain
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-postgres}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/swejobs_${STAMP}.sql.gz"

echo "[$(date -Is)] backing up -> $OUT"
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" \
  --data-only --disable-triggers --no-owner --no-privileges \
  | gzip > "$OUT"

# Prune old backups, keeping the newest $KEEP
ls -1t "$BACKUP_DIR"/swejobs_*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "[$(date -Is)] done; kept newest $KEEP backups"
