#!/usr/bin/env bash
# Non-destructive drill: restores an imaging snapshot into a disposable volume,
# boots the pinned Orthanc image, and proves its database can be opened.
set -euo pipefail

BACKUP_DIR="${IMAGING_BACKUP_DIR:-/backups/imaging}"
ORTHANC_IMAGE="${ORTHANC_IMAGE:-orthancteam/orthanc:26.6.1@sha256:83a1f988c9790a8ec018d00bad2d23d29703313e10ec59ecbeb827b5fa8e0aee}"
WORKDIR="$(mktemp -d)"
VOLUME="vitali-imaging-restore-drill-$$"
CONTAINER="vitali-imaging-restore-drill-$$"
fail() { echo "[imaging-restore-test] ERROR: $1" >&2; exit 1; }
cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  docker volume rm "${VOLUME}" >/dev/null 2>&1 || true
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || fail "docker is required"
ARTIFACT="${1:-$(find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name 'vitali_imaging_*.tar.gz' -o -name 'vitali_imaging_*.tar.gz.gpg' \) -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n1 | cut -d' ' -f2-)}"
[ -n "${ARTIFACT}" ] && [ -f "${ARTIFACT}" ] || fail "no imaging backup found"
if [ -f "${ARTIFACT}.sha256" ]; then (cd "$(dirname "${ARTIFACT}")" && sha256sum -c "$(basename "${ARTIFACT}").sha256"); fi

ARCHIVE="${ARTIFACT}"
case "${ARTIFACT}" in
  *.gpg)
    command -v gpg >/dev/null 2>&1 || fail "gpg is required"
    : "${BACKUP_ENCRYPTION_KEY:?required to decrypt the snapshot}"
    ARCHIVE="${WORKDIR}/snapshot.tar.gz"
    gpg --batch --yes --quiet --passphrase "${BACKUP_ENCRYPTION_KEY}" --output "${ARCHIVE}" --decrypt "${ARTIFACT}"
    ;;
esac
tar -tzf "${ARCHIVE}" | grep -q '^orthanc-data/' || fail "snapshot has no orthanc-data directory"
tar -tzf "${ARCHIVE}" | grep -q '^config/orthanc.json$' || fail "snapshot has no Orthanc config"
tar -xzf "${ARCHIVE}" -C "${WORKDIR}" config

docker volume create "${VOLUME}" >/dev/null
docker run --rm -v "${VOLUME}:/restore" -v "${ARCHIVE}:/snapshot.tar.gz:ro" alpine:3.22 \
  sh -c 'tar -xzf /snapshot.tar.gz -C /tmp orthanc-data && cp -a /tmp/orthanc-data/. /restore/'
docker run -d --name "${CONTAINER}" -v "${VOLUME}:/var/lib/orthanc/db" \
  -v "${WORKDIR}/config/orthanc.json:/etc/orthanc/orthanc.json:ro" \
  -v "${WORKDIR}/config/vitali-webhook.lua:/etc/orthanc/vitali-webhook.lua:ro" \
  -e ORTHANC__REGISTERED_USERS='{"restore-drill":"restore-drill"}' \
  "${ORTHANC_IMAGE}" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "${CONTAINER}" curl -fsS -u restore-drill:restore-drill http://127.0.0.1:8042/system >/dev/null 2>&1; then
    echo "[imaging-restore-test] PASS: $(basename "${ARTIFACT}") opened by ${ORTHANC_IMAGE}"
    exit 0
  fi
  sleep 2
done
docker logs "${CONTAINER}" >&2 || true
fail "restored archive did not become healthy"
