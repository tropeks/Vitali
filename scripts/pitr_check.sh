#!/usr/bin/env bash
# Fail-fast health/SLA check for PostgreSQL continuous WAL archiving.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PITR_COMPOSE_FILE="${PITR_COMPOSE_FILE:-docker-compose.pitr.yml}"
MAX_WAL_AGE_SECONDS="${PITR_MAX_WAL_AGE_SECONDS:-600}"
compose=(docker compose -f "${COMPOSE_FILE}" -f "${PITR_COMPOSE_FILE}")
fail() { echo "[pitr-check] ERROR: $1" >&2; exit 1; }
[[ "${MAX_WAL_AGE_SECONDS}" =~ ^[1-9][0-9]*$ ]] || fail "PITR_MAX_WAL_AGE_SECONDS must be positive"

CID="$("${compose[@]}" ps -q postgres)"
[ -n "${CID}" ] || fail "postgres container not found"
sql() {
  docker exec -u postgres "${CID}" psql -U "${POSTGRES_USER:-vitali}" -tAX \
    -d "${POSTGRES_DB:-vitali}" -c "$1"
}

[ "$(sql 'SHOW archive_mode;')" = on ] || fail "archive_mode is not on"
[ "$(sql 'SHOW wal_level;')" = replica ] || fail "wal_level is not replica"
ARCHIVE_COMMAND="$(sql 'SHOW archive_command;')"
[[ "${ARCHIVE_COMMAND}" == *'/wal-archive/'* ]] || fail "archive_command is not using the PITR volume"

if [ "${PITR_FORCE_SWITCH:-0}" = 1 ]; then
  TARGET_WAL="$(sql "SELECT pg_walfile_name(pg_switch_wal());")"
  for _ in $(seq 1 30); do
    [ "$(sql "SELECT coalesce(last_archived_wal,'');")" = "${TARGET_WAL}" ] && break
    sleep 1
  done
  [ "$(sql "SELECT coalesce(last_archived_wal,'');")" = "${TARGET_WAL}" ] \
    || fail "forced WAL ${TARGET_WAL} was not archived within 30s"
fi

STATS="$(sql "SELECT coalesce(archived_count,0)||'|'||coalesce(failed_count,0)||'|'||coalesce(extract(epoch from (now()-last_archived_time))::bigint,-1) FROM pg_stat_archiver;")"
IFS='|' read -r ARCHIVED FAILED AGE <<<"${STATS}"
[ "${FAILED}" -eq 0 ] || fail "pg_stat_archiver reports ${FAILED} failed archive operation(s)"
if [ "${PITR_FORCE_SWITCH:-0}" = 1 ] && [ "${ARCHIVED}" -gt 0 ] && [ "${AGE}" -gt "${MAX_WAL_AGE_SECONDS}" ]; then
  fail "last archived WAL is ${AGE}s old (limit ${MAX_WAL_AGE_SECONDS}s)"
fi

MOUNT_REF="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/wal-archive"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "${CID}")"
[ -n "${MOUNT_REF}" ] || fail "WAL archive volume is not mounted"
FILES="$(docker run --rm -v "${MOUNT_REF}:/wal:ro" alpine:3.22 sh -c "find /wal -maxdepth 1 -type f | wc -l")"
echo "[pitr-check] PASS: archived=${ARCHIVED}, failed=${FAILED}, last_age=${AGE}s, local_segments=${FILES}"
