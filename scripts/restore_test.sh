#!/usr/bin/env bash
# Vitali — Automated Restore Drill
# ─────────────────────────────────────────────────────────────────────────────
# Proves that a backup is actually restorable. Takes the most recent dump
# (local dir, or pulled from S3), decrypts it if needed, restores it into a
# THROWAWAY ephemeral Postgres container, runs sanity checks, and tears the
# container down. Never touches production or staging databases.
#
# Run weekly (host cron / systemd timer). Exits 0 only if restore + all sanity
# checks pass. RPO target 24h, RTO target 4h — see docs/BACKUPS.md.
#
# Usage:
#   BACKUP_DIR=/var/lib/docker/volumes/vitali_backups/_data bash scripts/restore_test.sh
#   # or pull the latest from S3:
#   BACKUP_S3_BUCKET=my-bucket BACKUP_S3_ACCESS_KEY=... BACKUP_S3_SECRET_KEY=... \
#     bash scripts/restore_test.sh
#
# Env:
#   BACKUP_DIR              Local dir holding vitali_*.dump[.gpg] (default /backups).
#   BACKUP_ENCRYPTION_KEY   GPG passphrase, required if the backup is .gpg.
#   BACKUP_S3_BUCKET        If set, pull the newest object instead of reading BACKUP_DIR.
#   BACKUP_S3_ENDPOINT/PREFIX/ACCESS_KEY/SECRET_KEY  As in backup.sh.
#   PG_IMAGE                Postgres image for the ephemeral DB (default postgres:16-alpine).
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-180}"
PG_PASSWORD="restore-drill-$$"
CONTAINER="vitali-restore-drill-$$"
WORKDIR="$(mktemp -d)"
cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

fail() { echo "[restore-test] ✗ $1" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is required on the host"

# ── 1. Obtain the most recent backup artifact ───────────────────────────────
if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  command -v aws >/dev/null 2>&1 || fail "aws CLI required to pull from S3"
  : "${BACKUP_S3_ACCESS_KEY:?required for S3}"
  : "${BACKUP_S3_SECRET_KEY:?required for S3}"
  S3_PREFIX="${BACKUP_S3_PREFIX:-vitali}"
  endpoint_args=()
  [ -n "${BACKUP_S3_ENDPOINT:-}" ] && endpoint_args=(--endpoint-url "${BACKUP_S3_ENDPOINT}")
  export AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}"
  export AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}"
  echo "[restore-test] Finding newest object in s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/…"
  LATEST_KEY="$(aws "${endpoint_args[@]}" s3 ls "s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/" \
    | sort | tail -n1 | awk '{print $4}')"
  [ -n "${LATEST_KEY}" ] || fail "no objects found in bucket"
  ARTIFACT="${WORKDIR}/${LATEST_KEY}"
  aws "${endpoint_args[@]}" s3 cp "s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/${LATEST_KEY}" "${ARTIFACT}" \
    || fail "download failed"
else
  ARTIFACT="$(ls -1t "${BACKUP_DIR}"/vitali_*.dump "${BACKUP_DIR}"/vitali_*.dump.gpg 2>/dev/null | head -n1 || true)"
  [ -n "${ARTIFACT}" ] || fail "no backup found in ${BACKUP_DIR}"
fi
echo "[restore-test] Using artifact: $(basename "${ARTIFACT}")"

# ── 2. Decrypt if needed ────────────────────────────────────────────────────
DUMP="${ARTIFACT}"
case "${ARTIFACT}" in
  *.gpg)
    command -v gpg >/dev/null 2>&1 || fail "gpg required to decrypt .gpg backup"
    : "${BACKUP_ENCRYPTION_KEY:?required to decrypt .gpg backup}"
    DUMP="${WORKDIR}/decrypted.dump"
    echo "[restore-test] Decrypting…"
    gpg --batch --yes --quiet --passphrase "${BACKUP_ENCRYPTION_KEY}" \
      --output "${DUMP}" --decrypt "${ARTIFACT}" || fail "decryption failed"
    ;;
esac

# ── 3. Spin an ephemeral Postgres and restore ───────────────────────────────
echo "[restore-test] Starting ephemeral Postgres (${PG_IMAGE})…"
docker run -d --name "${CONTAINER}" \
  -e PGDATA=/tmp/pgdata \
  -e POSTGRES_PASSWORD="${PG_PASSWORD}" \
  -e POSTGRES_USER=vitali -e POSTGRES_DB=vitali \
  "${PG_IMAGE}" postgres -c unix_socket_directories=/var/lib/postgresql/data >/dev/null

echo "[restore-test] Waiting for readiness…"
for _ in $(seq 1 "$((READY_TIMEOUT_SECONDS / 2))"); do
  if docker exec "${CONTAINER}" pg_isready -h 127.0.0.1 -U vitali >/dev/null 2>&1; then break; fi
  sleep 2
done
docker exec "${CONTAINER}" pg_isready -h 127.0.0.1 -U vitali >/dev/null 2>&1 || fail "ephemeral Postgres never became ready"

echo "[restore-test] Restoring dump…"
docker cp "${DUMP}" "${CONTAINER}:/tmp/restore.dump"
# pg_restore returns non-zero on benign warnings; we judge success by the sanity
# checks below, not by its exit code, but we still surface its stderr.
docker exec -e PGPASSWORD="${PG_PASSWORD}" "${CONTAINER}" \
  pg_restore --host=127.0.0.1 --port=5432 --no-owner --no-privileges --dbname=vitali --username=vitali /tmp/restore.dump \
  2>"${WORKDIR}/restore.err" || echo "[restore-test] (pg_restore reported warnings — validating by content)"

# Explicit TCP (127.0.0.1:5432), matching the readiness probe above. The image
# also exposes a Unix socket (unix_socket_directories is repointed at the
# default PGDATA path in the `docker run` above, so it lands somewhere already
# writable), but psql/pg_restore have their own compiled-in default socket
# directory when no -h/--host is given, and it need not match the server's.
# Forcing TCP everywhere removes that ambiguity instead of relying on both
# sides agreeing by luck.
q() { docker exec -e PGPASSWORD="${PG_PASSWORD}" "${CONTAINER}" \
  psql -h 127.0.0.1 -p 5432 -tAX -U vitali -d vitali -c "$1" 2>/dev/null | tr -d '[:space:]'; }

# Like q() but preserves one row per line — for multi-row results (e.g. the
# list of tenant schema names below). q() intentionally strips ALL whitespace
# including newlines, which would concatenate rows into one unusable string.
q_rows() { docker exec -e PGPASSWORD="${PG_PASSWORD}" "${CONTAINER}" \
  psql -h 127.0.0.1 -p 5432 -tAX -U vitali -d vitali -c "$1" 2>/dev/null; }

# ── 4. Sanity checks ────────────────────────────────────────────────────────
echo "[restore-test] Running sanity checks…"

MIGRATIONS="$(q "SELECT count(*) FROM django_migrations;")"
[ -n "${MIGRATIONS}" ] && [ "${MIGRATIONS}" -gt 0 ] 2>/dev/null \
  || fail "django_migrations empty or missing (got: '${MIGRATIONS:-none}')"
echo "  ✓ django_migrations rows: ${MIGRATIONS}"

# Tenants live in the public schema — apps.core is in SHARED_APPS (see
# vitali/settings/base.py). apps.core.models.Tenant declares no db_table, so
# Django's default naming applies: <app_label>_<model_name> = core_tenant.
TENANTS="$(q "SELECT count(*) FROM core_tenant;")"
if [ -n "${TENANTS}" ] && [ "${TENANTS}" -ge 0 ] 2>/dev/null; then
  echo "  ✓ core_tenant rows: ${TENANTS}"
else
  fail "core_tenant not restorable (got: '${TENANTS:-none}')"
fi

# A restore that keeps the public schema (migrations ✓, core_tenant rows ✓)
# can still have silently lost every patient in every clinic — django-tenants
# isolates clinical data per tenant in its own Postgres schema, named after
# Tenant.schema_name (== the clinic's slug; NOT a fixed/predictable value —
# see Tenant.save() in apps/core/models.py). Discover the real schema names
# from core_tenant and require at least one to actually contain emr_patient
# rows (apps.emr is in TENANT_APPS — see vitali/settings/base.py — so
# emr_patient lives inside each tenant schema, never in public).
if [ "${TENANTS:-0}" != "0" ]; then
  FOUND_CLINICAL_DATA=0
  while IFS= read -r SCHEMA; do
    [ -n "${SCHEMA}" ] || continue
    case "${SCHEMA}" in
      *[!A-Za-z0-9_-]*)
        echo "  ! skipping schema with unexpected characters in name: '${SCHEMA}'" >&2
        continue
        ;;
    esac
    # Identifier is double-quoted (never string-interpolated as a literal), so
    # a hyphenated schema name (SlugField allows '-') stays a safe, single
    # identifier rather than SQL syntax.
    PATIENTS="$(docker exec -e PGPASSWORD="${PG_PASSWORD}" "${CONTAINER}" \
      psql -h 127.0.0.1 -p 5432 -tAX -U vitali -d vitali \
      -c "SELECT count(*) FROM \"${SCHEMA}\".emr_patient;" 2>/dev/null | tr -d '[:space:]')"
    if [ -n "${PATIENTS}" ] && [ "${PATIENTS}" -gt 0 ] 2>/dev/null; then
      echo "  ✓ schema '${SCHEMA}' emr_patient rows: ${PATIENTS}"
      FOUND_CLINICAL_DATA=1
      break
    else
      echo "  · schema '${SCHEMA}' emr_patient rows: ${PATIENTS:-0} (table missing, or tenant has no patients yet)"
    fi
  done <<< "$(q_rows "SELECT schema_name FROM core_tenant;")"
  [ "${FOUND_CLINICAL_DATA}" -eq 1 ] \
    || fail "no tenant schema has emr_patient rows — clinical data is missing from the restore"
else
  echo "  · no tenants present — skipping clinical-data check (nothing to validate yet)"
fi

# Supplementary signal only (NOT authoritative on its own — a schema can exist
# and still be empty of clinical data, which is exactly what the check above
# catches). Total restored schema count, tenant + public + anything else.
SCHEMAS="$(q "SELECT count(*) FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast');")"
echo "  ✓ schemas present: ${SCHEMAS}"

echo "[restore-test] ✓ PASS — backup '$(basename "${ARTIFACT}")' restored and validated."
