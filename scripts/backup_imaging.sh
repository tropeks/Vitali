#!/usr/bin/env bash
# Consistent cold snapshot of the Orthanc archive volume and its runtime config.
# Orthanc is stopped only for the tar operation and is always restarted on exit.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${IMAGING_BACKUP_DIR:-/backups/imaging}"
KEEP_LAST="${IMAGING_BACKUP_KEEP_LAST:-7}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
ARCHIVE="vitali_imaging_${TIMESTAMP}.tar.gz"

fail() { echo "[imaging-backup] ERROR: $1" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "docker is required"
[ -f "${COMPOSE_FILE}" ] || fail "compose file not found: ${COMPOSE_FILE}"
[ -f docker/orthanc/orthanc.json ] || fail "run from the Vitali repository root"
[[ "${KEEP_LAST}" =~ ^[1-9][0-9]*$ ]] || fail "IMAGING_BACKUP_KEEP_LAST must be a positive integer"

mkdir -p "${BACKUP_DIR}"
BACKUP_DIR="$(cd "${BACKUP_DIR}" && pwd -P)"
CID="$(docker compose -f "${COMPOSE_FILE}" ps -q orthanc)"
[ -n "${CID}" ] || fail "Orthanc container does not exist for ${COMPOSE_FILE}"

WAS_RUNNING="$(docker inspect -f '{{.State.Running}}' "${CID}")"
restart_archive() {
  if [ "${WAS_RUNNING}" = true ]; then
    docker compose -f "${COMPOSE_FILE}" start orthanc >/dev/null 2>&1 || true
  fi
}
trap restart_archive EXIT

echo "[imaging-backup] Stopping archive for a consistent snapshot…"
docker compose -f "${COMPOSE_FILE}" stop -t 60 orthanc >/dev/null

MOUNT_TYPE="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/orthanc/db"}}{{.Type}}{{end}}{{end}}' "${CID}")"
MOUNT_REF="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/orthanc/db"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "${CID}")"
[ -n "${MOUNT_REF}" ] || fail "could not resolve /var/lib/orthanc/db mount"

echo "[imaging-backup] Creating ${ARCHIVE} from ${MOUNT_TYPE} storage…"
docker run --rm \
  -v "${MOUNT_REF}:/snapshot/orthanc-data:ro" \
  -v "${PWD}/docker/orthanc:/snapshot/config:ro" \
  -v "${BACKUP_DIR}:/backup" \
  alpine:3.22 tar -czf "/backup/${ARCHIVE}" -C /snapshot orthanc-data config

# Minimize the ingest outage before checksums/encryption/upload work.
restart_archive
WAS_RUNNING=false
trap - EXIT

(cd "${BACKUP_DIR}" && sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256")
tar -tzf "${BACKUP_DIR}/${ARCHIVE}" >/dev/null || fail "archive verification failed"

if [ -n "${BACKUP_ENCRYPTION_KEY:-}" ]; then
  command -v gpg >/dev/null 2>&1 || fail "gpg required when BACKUP_ENCRYPTION_KEY is set"
  gpg --batch --yes --quiet --passphrase "${BACKUP_ENCRYPTION_KEY}" --cipher-algo AES256 \
    --symmetric --output "${BACKUP_DIR}/${ARCHIVE}.gpg" "${BACKUP_DIR}/${ARCHIVE}"
  rm -f "${BACKUP_DIR}/${ARCHIVE}" "${BACKUP_DIR}/${ARCHIVE}.sha256"
  ARCHIVE="${ARCHIVE}.gpg"
  (cd "${BACKUP_DIR}" && sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256")
fi

if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  command -v aws >/dev/null 2>&1 || fail "aws CLI required for offsite upload"
  : "${BACKUP_S3_ACCESS_KEY:?required for S3}"
  : "${BACKUP_S3_SECRET_KEY:?required for S3}"
  PREFIX="${BACKUP_S3_PREFIX:-vitali}/imaging"
  endpoint_args=()
  [ -n "${BACKUP_S3_ENDPOINT:-}" ] && endpoint_args=(--endpoint-url "${BACKUP_S3_ENDPOINT}")
  AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
    aws "${endpoint_args[@]}" s3 cp "${BACKUP_DIR}/${ARCHIVE}" \
    "s3://${BACKUP_S3_BUCKET}/${PREFIX}/${ARCHIVE}"
fi

mapfile -t OLD < <(find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name 'vitali_imaging_*.tar.gz' -o -name 'vitali_imaging_*.tar.gz.gpg' \) -printf '%T@ %p\n' | sort -rn | tail -n "+$((KEEP_LAST + 1))" | cut -d' ' -f2-)
for old in "${OLD[@]}"; do rm -f -- "${old}" "${old}.sha256"; done
echo "[imaging-backup] PASS: ${BACKUP_DIR}/${ARCHIVE}"
