#!/usr/bin/env bash
# Online physical base backup, written directly to a host-only 0700 directory.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
OUTPUT_ROOT="${PITR_BASEBACKUP_DIR:-/var/backups/vitali/pitr/base}"
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
KEEP_LAST="${PITR_BASEBACKUP_KEEP_LAST:-5}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${OUTPUT_ROOT}/base_${TIMESTAMP}"
fail() { echo "[pitr-basebackup] ERROR: $1" >&2; exit 1; }
[[ "${KEEP_LAST}" =~ ^[1-9][0-9]*$ ]] || fail "PITR_BASEBACKUP_KEEP_LAST must be positive"

CID="$(docker compose -f "${COMPOSE_FILE}" ps -q postgres)"
[ -n "${CID}" ] || fail "postgres container not found"
PASSWORD="$(docker exec "${CID}" sh -c 'printf %s "$POSTGRES_PASSWORD"')"
[ -n "${PASSWORD}" ] || fail "POSTGRES_PASSWORD is unavailable in the container"
install -d -m 0700 "${OUTPUT_ROOT}" "${DEST}"
NETMODE="container:${CID}"

echo "[pitr-basebackup] Streaming physical backup to ${DEST}…"
docker run --rm --network "${NETMODE}" \
  -e PGPASSWORD="${PASSWORD}" -v "${DEST}:/backup" "${PG_IMAGE}" \
  pg_basebackup -h 127.0.0.1 -p 5432 -U "${POSTGRES_USER:-vitali}" \
    -D /backup -Fp -Xs -c fast --manifest-checksums=SHA256 --no-password --verbose
docker run --rm -v "${DEST}:/backup:ro" "${PG_IMAGE}" pg_verifybackup /backup

if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  command -v aws >/dev/null 2>&1 || fail "aws CLI required for offsite upload"
  : "${BACKUP_S3_ACCESS_KEY:?required for S3}"
  : "${BACKUP_S3_SECRET_KEY:?required for S3}"
  PREFIX="${BACKUP_S3_PREFIX:-vitali}/pitr/base"
  endpoint_args=()
  [ -n "${BACKUP_S3_ENDPOINT:-}" ] && endpoint_args=(--endpoint-url "${BACKUP_S3_ENDPOINT}")
  if [ -n "${BACKUP_ENCRYPTION_KEY:-}" ]; then
    command -v gpg >/dev/null 2>&1 || fail "gpg required to encrypt the offsite base backup"
    ARTIFACT="${OUTPUT_ROOT}/base_${TIMESTAMP}.tar.gpg"
    tar -C "${OUTPUT_ROOT}" -cf - "base_${TIMESTAMP}" | gpg --batch --yes --quiet \
      --passphrase "${BACKUP_ENCRYPTION_KEY}" --cipher-algo AES256 --symmetric --output "${ARTIFACT}"
    AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
      aws "${endpoint_args[@]}" s3 cp "${ARTIFACT}" "s3://${BACKUP_S3_BUCKET}/${PREFIX}/$(basename "${ARTIFACT}")" --only-show-errors
  elif [ "${PITR_ALLOW_UNENCRYPTED_OFFSITE:-0}" = 1 ]; then
    AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
      aws "${endpoint_args[@]}" s3 sync "${DEST}/" "s3://${BACKUP_S3_BUCKET}/${PREFIX}/base_${TIMESTAMP}/" --only-show-errors
  else
    fail "BACKUP_ENCRYPTION_KEY is required for offsite base backups (or explicitly set PITR_ALLOW_UNENCRYPTED_OFFSITE=1)"
  fi
fi

# A verified newer base plus continuous WAL makes older local bases redundant.
# Pruning is restricted to the exact base_TIMESTAMP directories under OUTPUT_ROOT.
mapfile -t OLD_BASES < <(find "${OUTPUT_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'base_[0-9]*T[0-9]*Z' -printf '%T@ %p\n' | sort -rn | tail -n "+$((KEEP_LAST + 1))" | cut -d' ' -f2-)
for old in "${OLD_BASES[@]}"; do
  [[ "$(basename "${old}")" =~ ^base_[0-9]{8}T[0-9]{6}Z$ ]] || fail "refusing unexpected prune target: ${old}"
  rm -rf -- "${old}"
done
echo "[pitr-basebackup] PASS: ${DEST}"
