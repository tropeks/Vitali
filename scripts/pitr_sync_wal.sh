#!/usr/bin/env bash
# Idempotently ships completed WAL segments from the archive volume to S3.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PITR_COMPOSE_FILE="${PITR_COMPOSE_FILE:-docker-compose.pitr.yml}"
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required}"
: "${BACKUP_S3_ACCESS_KEY:?BACKUP_S3_ACCESS_KEY is required}"
: "${BACKUP_S3_SECRET_KEY:?BACKUP_S3_SECRET_KEY is required}"
command -v aws >/dev/null 2>&1 || { echo "[pitr-wal-sync] ERROR: aws CLI is required" >&2; exit 1; }

CID="$(docker compose -f "${COMPOSE_FILE}" -f "${PITR_COMPOSE_FILE}" ps -q postgres)"
[ -n "${CID}" ] || { echo "[pitr-wal-sync] ERROR: postgres container not found" >&2; exit 1; }
SOURCE="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/wal-archive"}}{{.Source}}{{end}}{{end}}' "${CID}")"
[ -n "${SOURCE}" ] || { echo "[pitr-wal-sync] ERROR: WAL archive mount not found" >&2; exit 1; }
PREFIX="${BACKUP_S3_PREFIX:-vitali}/pitr/wal"
SSE="${PITR_S3_SSE:-AES256}"
endpoint_args=()
[ -n "${BACKUP_S3_ENDPOINT:-}" ] && endpoint_args=(--endpoint-url "${BACKUP_S3_ENDPOINT}")

AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
  aws "${endpoint_args[@]}" s3 sync "${SOURCE}/" "s3://${BACKUP_S3_BUCKET}/${PREFIX}/" \
    --exclude '*.tmp' --sse "${SSE}" --only-show-errors
echo "[pitr-wal-sync] PASS: completed WAL segments synchronized"
