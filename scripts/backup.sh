#!/usr/bin/env bash
# pg_dump backup with timestamped custom-format files and a keep-last-N retention policy.
# Runs inside the db-backup container (daily at 02:00 UTC) or manually via `make backup`.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_LAST="${KEEP_LAST:-7}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
BACKUP_FILE="${BACKUP_DIR}/vitali_${TIMESTAMP}.dump"

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:=vitali}"
: "${POSTGRES_USER:=vitali}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

mkdir -p "${BACKUP_DIR}"

echo "[backup] $(date -u +%FT%TZ) — dumping ${POSTGRES_DB}@${POSTGRES_HOST}:${POSTGRES_PORT}"
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --format=custom \
  --file="${BACKUP_FILE}" \
  "${POSTGRES_DB}"

SIZE="$(du -sh "${BACKUP_FILE}" | cut -f1)"
echo "[backup] Written: ${BACKUP_FILE} (${SIZE})"

# Retention: delete dumps older than the KEEP_LAST most-recent ones.
OLD_DUMPS="$(ls -1t "${BACKUP_DIR}"/*.dump 2>/dev/null | tail -n "+$((KEEP_LAST + 1))")"
if [ -n "${OLD_DUMPS}" ]; then
  echo "[backup] Pruning $(echo "${OLD_DUMPS}" | wc -l | tr -d ' ') old backup(s)..."
  echo "${OLD_DUMPS}" | xargs rm -v
fi

echo "[backup] Done — ${KEEP_LAST} most-recent backup(s) retained in ${BACKUP_DIR}"
