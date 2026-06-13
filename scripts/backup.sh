#!/usr/bin/env bash
# pg_dump backup with timestamped custom-format files, optional GPG encryption,
# optional offsite upload to an S3-compatible bucket, and a keep-last-N local
# retention policy.
#
# Runs inside the db-backup container (daily at 02:00 UTC) or manually via `make backup`.
#
# Local-only behaviour (no S3/encryption envs set) is unchanged from the original
# script, so existing staging deployments keep working without new configuration.
#
# Optional offsite + encryption (set in .env.production):
#   BACKUP_ENCRYPTION_KEY   GPG symmetric passphrase. If set, the dump is encrypted
#                           with AES256 before it ever leaves the box (.dump.gpg).
#   BACKUP_S3_BUCKET        Bucket name. If set, the (encrypted) dump is uploaded.
#   BACKUP_S3_ENDPOINT      Optional custom endpoint (e.g. Backblaze B2:
#                           https://s3.us-west-002.backblazeb2.com). Omit for AWS S3.
#   BACKUP_S3_PREFIX        Optional key prefix inside the bucket (default: vitali).
#   BACKUP_S3_ACCESS_KEY    S3 access key id.
#   BACKUP_S3_SECRET_KEY    S3 secret access key.
#
# Required tools when those envs are set: `gpg` (encryption) and `aws` (upload).
# The db-backup container installs them at startup (see docker-compose.prod.yml).
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

# The artifact we retain/upload — becomes the .gpg file if encryption is enabled.
ARTIFACT="${BACKUP_FILE}"

# ── Optional encryption (GPG symmetric AES256) ──────────────────────────────
if [ -n "${BACKUP_ENCRYPTION_KEY:-}" ]; then
  if ! command -v gpg >/dev/null 2>&1; then
    echo "[backup] ERROR: BACKUP_ENCRYPTION_KEY set but 'gpg' is not installed" >&2
    exit 1
  fi
  echo "[backup] Encrypting (AES256)…"
  gpg --batch --yes --quiet \
    --passphrase "${BACKUP_ENCRYPTION_KEY}" \
    --cipher-algo AES256 \
    --symmetric \
    --output "${BACKUP_FILE}.gpg" \
    "${BACKUP_FILE}"
  rm -f "${BACKUP_FILE}"            # never keep the plaintext dump once encrypted
  ARTIFACT="${BACKUP_FILE}.gpg"
  echo "[backup] Encrypted: ${ARTIFACT}"
fi

# ── Optional offsite upload (S3-compatible) ─────────────────────────────────
if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  if ! command -v aws >/dev/null 2>&1; then
    echo "[backup] ERROR: BACKUP_S3_BUCKET set but 'aws' CLI is not installed" >&2
    exit 1
  fi
  : "${BACKUP_S3_ACCESS_KEY:?BACKUP_S3_ACCESS_KEY is required when BACKUP_S3_BUCKET is set}"
  : "${BACKUP_S3_SECRET_KEY:?BACKUP_S3_SECRET_KEY is required when BACKUP_S3_BUCKET is set}"
  S3_PREFIX="${BACKUP_S3_PREFIX:-vitali}"
  S3_KEY="s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/$(basename "${ARTIFACT}")"

  endpoint_args=()
  [ -n "${BACKUP_S3_ENDPOINT:-}" ] && endpoint_args=(--endpoint-url "${BACKUP_S3_ENDPOINT}")

  echo "[backup] Uploading to ${S3_KEY}…"
  if ! AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" \
       AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
       aws "${endpoint_args[@]}" s3 cp "${ARTIFACT}" "${S3_KEY}"; then
    echo "[backup] ERROR: offsite upload failed for ${ARTIFACT}" >&2
    exit 1
  fi
  echo "[backup] Uploaded: ${S3_KEY}"
fi

# ── Local retention (delete dumps older than the KEEP_LAST most-recent) ─────
# Matches both .dump and .dump.gpg artifacts.
OLD_DUMPS="$(ls -1t "${BACKUP_DIR}"/vitali_*.dump "${BACKUP_DIR}"/vitali_*.dump.gpg 2>/dev/null | tail -n "+$((KEEP_LAST + 1))")"
if [ -n "${OLD_DUMPS}" ]; then
  echo "[backup] Pruning $(echo "${OLD_DUMPS}" | wc -l | tr -d ' ') old backup(s)…"
  echo "${OLD_DUMPS}" | xargs rm -v
fi

echo "[backup] Done — ${KEEP_LAST} most-recent backup(s) retained in ${BACKUP_DIR}"
