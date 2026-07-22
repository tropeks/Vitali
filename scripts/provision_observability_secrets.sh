#!/usr/bin/env bash
# Materialize exporter/Grafana secret files outside the repository.
set -euo pipefail

ENV_FILE="${PROD_ENV_FILE:-/etc/vitali/secrets.env}"
SECRET_DIR="${OBSERVABILITY_SECRET_DIR:-/etc/vitali}"
[ "$(id -u)" -eq 0 ] || { echo "Run as root" >&2; exit 1; }
[ -r "${ENV_FILE}" ] || { echo "Cannot read ${ENV_FILE}" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in ${ENV_FILE}}"
: "${REDIS_PASSWORD:?REDIS_PASSWORD is required in ${ENV_FILE}}"
command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }

install -d -m 0700 "${SECRET_DIR}"
umask 0077
printf '%s' "${POSTGRES_PASSWORD}" > "${SECRET_DIR}/postgres-exporter-password"
jq -cn --arg password "${REDIS_PASSWORD}" \
  '{"redis://redis:6379": $password}' > "${SECRET_DIR}/redis-exporter-passwords.json"
if [ ! -s "${SECRET_DIR}/grafana-admin-password" ]; then
  openssl rand -base64 36 | tr -d '\n' > "${SECRET_DIR}/grafana-admin-password"
fi
# The directory is root-only. Read-only file mode lets fixed non-root container
# UIDs consume individual bind mounts without granting host directory traversal.
chmod 0444 "${SECRET_DIR}/postgres-exporter-password" \
  "${SECRET_DIR}/redis-exporter-passwords.json" "${SECRET_DIR}/grafana-admin-password"
echo "Observability secret files provisioned in ${SECRET_DIR} (values not displayed)."
