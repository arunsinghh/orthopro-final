#!/usr/bin/env bash
# Encrypted PostgreSQL backup with retention.
#
# Schedule via cron, e.g. daily at 02:30:
#   30 2 * * * /path/to/orthopro/scripts/backup.sh >> /var/log/orthopro-backup.log 2>&1
#
# Requires env (do NOT hardcode here):
#   DATABASE_URL          postgresql://user:pass@host:5432/db
#   BACKUP_DIR            where backups are written (default ./backups)
#   BACKUP_PASSPHRASE     passphrase for AES-256 encryption
#   BACKUP_RETENTION_DAYS days to keep (default 14)
#
# Restore (disaster recovery):
#   openssl enc -d -aes-256-cbc -pbkdf2 -in FILE.sql.gz.enc | gunzip | psql "$DATABASE_URL"
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is required}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/orthopro-${STAMP}.sql.gz.enc"

mkdir -p "$BACKUP_DIR"

pg_dump "$DATABASE_URL" --no-owner --no-privileges \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$OUT"

chmod 600 "$OUT"
echo "[backup] wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Retention: remove encrypted backups older than the retention window.
find "$BACKUP_DIR" -name 'orthopro-*.sql.gz.enc' -mtime "+${RETENTION_DAYS}" -print -delete

# Reminder: periodically test a restore (see SECURITY.md / DATABASE.md).
echo "[backup] done. Remember to periodically test a restore."
