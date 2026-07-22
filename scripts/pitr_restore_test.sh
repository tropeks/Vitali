#!/usr/bin/env bash
# Non-destructive physical restore/recovery drill in disposable Docker volumes.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PITR_COMPOSE_FILE="${PITR_COMPOSE_FILE:-docker-compose.pitr.yml}"
BASE_ROOT="${PITR_BASEBACKUP_DIR:-/var/backups/vitali/pitr/base}"
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
DATA_VOLUME="vitali-pitr-drill-data-$$"
WAL_VOLUME="vitali-pitr-drill-wal-$$"
CONTAINER="vitali-pitr-drill-$$"
fail() { echo "[pitr-restore-test] ERROR: $1" >&2; exit 1; }
cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  docker volume rm "${DATA_VOLUME}" "${WAL_VOLUME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

BASE="${1:-$(find "${BASE_ROOT}" -mindepth 1 -maxdepth 1 -type d -name 'base_*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n1 | cut -d' ' -f2-)}"
[ -n "${BASE}" ] && [ -f "${BASE}/backup_manifest" ] || fail "valid base backup not found"
docker run --rm -v "${BASE}:/backup:ro" "${PG_IMAGE}" pg_verifybackup /backup

SOURCE_CID="$(docker compose -f "${COMPOSE_FILE}" -f "${PITR_COMPOSE_FILE}" ps -q postgres)"
[ -n "${SOURCE_CID}" ] || fail "source postgres container not found"
WAL_REF="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/wal-archive"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "${SOURCE_CID}")"
[ -n "${WAL_REF}" ] || fail "WAL archive volume not found"

docker volume create "${DATA_VOLUME}" >/dev/null
docker volume create "${WAL_VOLUME}" >/dev/null
docker run --rm -v "${BASE}:/source:ro" -v "${DATA_VOLUME}:/target" alpine:3.22 \
  sh -c 'cp -a /source/. /target/ && touch /target/recovery.signal && printf "restore_command = '\''cp /wal-archive/%f %p'\''\nrecovery_target_action = '\''promote'\''\n" >> /target/postgresql.auto.conf && chown -R 70:70 /target'
docker run --rm -v "${WAL_REF}:/source:ro" -v "${WAL_VOLUME}:/target" alpine:3.22 \
  sh -c 'cp -a /source/. /target/'
docker run -d --name "${CONTAINER}" -v "${DATA_VOLUME}:/var/lib/postgresql/data" \
  -v "${WAL_VOLUME}:/wal-archive:ro" "${PG_IMAGE}" >/dev/null

for _ in $(seq 1 60); do
  if docker exec -u postgres "${CONTAINER}" pg_isready -U "${POSTGRES_USER:-vitali}" >/dev/null 2>&1; then
    ROWS="$(docker exec -u postgres "${CONTAINER}" psql -tAX -U "${POSTGRES_USER:-vitali}" -d "${POSTGRES_DB:-vitali}" -c 'SELECT count(*) FROM django_migrations;' | tr -d '[:space:]')"
    [ "${ROWS}" -gt 0 ] || fail "restored django_migrations is empty"
    echo "[pitr-restore-test] PASS: base=$(basename "${BASE}"), migrations=${ROWS}"
    exit 0
  fi
  sleep 2
done
docker logs "${CONTAINER}" >&2 || true
fail "recovered cluster did not become ready"
