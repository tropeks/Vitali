#!/usr/bin/env bash
# pg_dump backup with timestamped custom-format files, GPG encryption (required
# by default — see BACKUP_ENCRYPTION_KEY below), optional offsite upload to an
# S3-compatible bucket, and a keep-last-N local retention policy.
#
# Runs inside the db-backup container (daily at 02:00 UTC in staging/prod — see
# docker-compose.staging.yml / docker-compose.prod.yml), or manually, e.g.
# `docker compose -f docker-compose.staging.yml exec db-backup /usr/local/bin/backup.sh`
# (see docs/BACKUPS.md). NOTE: `make backup` is a DIFFERENT, simpler code path
# (plain `pg_dump` via `docker compose exec postgres`, unencrypted) — it does
# not call this script and is unaffected by BACKUP_ENCRYPTION_KEY below.
#
# BACKUP_ENCRYPTION_KEY   GPG symmetric passphrase. REQUIRED: the dump contains
#                         LGPD-regulated clinical data (EMR — apps.emr, see
#                         backend/apps/emr/models.py), so it is always encrypted
#                         with AES256 (.dump.gpg) before this script exits
#                         successfully. Generate one with scripts/gen_secrets.sh
#                         and store it in an offline vault — losing it makes
#                         every encrypted dump unrecoverable, guard it like
#                         FIELD_ENCRYPTION_KEY. To explicitly run without
#                         encryption (e.g. a throwaway staging/pilot box with no
#                         real patient data), set BACKUP_ALLOW_PLAINTEXT=1.
# BACKUP_S3_BUCKET        Bucket name. If set, the (always-encrypted) dump is
#                         uploaded.
# BACKUP_S3_ENDPOINT      Optional custom endpoint (e.g. Backblaze B2:
#                         https://s3.us-west-002.backblazeb2.com). Omit for AWS S3.
# BACKUP_S3_PREFIX        Optional key prefix inside the bucket (default: vitali).
#                         Os objetos vao para <prefix>/daily/ e, uma vez por
#                         competencia, tambem para <prefix>/monthly/ — e o que
#                         torna possivel a retencao GFS por lifecycle do bucket.
# BACKUP_S3_COMPAT        'r2' liga o contorno de checksum do Cloudflare R2
#                         (CRC32 nao implementado la). Vazio/'b2'/'aws' = padrao.
# BACKUP_S3_ACCESS_KEY    S3 access key id.
# BACKUP_S3_SECRET_KEY    S3 secret access key.
#
# Required tools: `gpg` (encryption, always) and `aws` (upload, when BACKUP_S3_*
# is set). The db-backup container installs them at startup (see
# docker-compose.prod.yml / docker-compose.staging.yml).
#
# vitali/settings/production.py additionally refuses to boot django/celery
# (production AND staging both run DJANGO_SETTINGS_MODULE=vitali.settings.
# production) when BACKUP_ENCRYPTION_KEY is unset and BACKUP_ALLOW_PLAINTEXT
# is not set — see the comment there for why that check exists in ADDITION to
# this one rather than instead of it.
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

# BACKUP_ENCRYPTION_KEY is required — fail before spending any I/O on a dump we
# would otherwise have to write to disk in plaintext (LGPD-regulated clinical
# data). This is the primary guard: db-backup runs in a bare postgres:16-alpine
# container that never loads Django, so vitali/settings/production.py's own
# check on this same variable cannot see (or stop) a misconfigured nightly cron
# run by itself — it only stops django/celery from booting.
if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ] && [ "${BACKUP_ALLOW_PLAINTEXT:-0}" != "1" ]; then
  echo "[backup] ERROR: BACKUP_ENCRYPTION_KEY is not set. Dumps contain LGPD-regulated" >&2
  echo "[backup] clinical data (EMR) and must not be written to disk unencrypted." >&2
  echo "[backup] Generate a key with scripts/gen_secrets.sh and store it in an offline" >&2
  echo "[backup] vault, or explicitly acknowledge an unencrypted local/dev run with" >&2
  echo "[backup] BACKUP_ALLOW_PLAINTEXT=1." >&2
  exit 1
fi

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

# The artifact we retain/upload — becomes the .gpg file whenever a key is set
# (the default-required case; see the guard above). Only a deliberate
# BACKUP_ALLOW_PLAINTEXT=1 run reaches here with no key.
ARTIFACT="${BACKUP_FILE}"

# ── Encryption (GPG symmetric AES256) ───────────────────────────────────────
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
else
  echo "[backup] WARNING: BACKUP_ALLOW_PLAINTEXT=1 — dump left UNENCRYPTED at ${ARTIFACT}" >&2
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
  ARTIFACT_BASE="$(basename "${ARTIFACT}")"

  endpoint_args=()
  [ -n "${BACKUP_S3_ENDPOINT:-}" ] && endpoint_args=(--endpoint-url "${BACKUP_S3_ENDPOINT}")

  # ── Compatibilidade do provedor ──────────────────────────────────────────
  # BACKUP_S3_COMPAT=r2 liga o contorno do Cloudflare R2: as SDKs/CLI recentes
  # da AWS mandam checksum CRC32 por padrao em PutObject/UploadPart, e o R2
  # recusa com
  #   Header 'x-amz-checksum-algorithm' with value 'CRC32' not implemented
  # Sem isto o upload falha, e a mensagem nao se parece com "faltou configurar".
  # Vazio (ou 'b2'/'aws') = comportamento padrao, que e o que B2 e S3 esperam.
  if [ "${BACKUP_S3_COMPAT:-}" = "r2" ]; then
    export AWS_REQUEST_CHECKSUM_CALCULATION="when_required"
    export AWS_RESPONSE_CHECKSUM_VALIDATION="when_required"
    echo "[backup] Provedor R2: checksum em modo when_required"
  fi

  # ── Retencao GFS: quem separa diario de mensal e o uploader ──────────────
  # Todo artefato se chama vitali_<timestamp>.dump.gpg — o nome nao distingue
  # diario de mensal. E regra de lifecycle de bucket opera por IDADE e PREFIXO,
  # nunca por "guarde o primeiro de cada mes". Entao o esquema 30 diarios + 12
  # mensais so existe se o upload colocar os dois em prefixos diferentes:
  #   <prefix>/daily/    → lifecycle expira em 30 dias
  #   <prefix>/monthly/  → lifecycle expira em 365 dias
  # O mensal e uma COPIA do mesmo artefato (25 MB, uma vez por mes), nao um
  # dump separado: cifrado com a mesma chave, identico byte a byte ao diario.
  s3_upload() {
    local destino="$1"
    echo "[backup] Uploading to ${destino}…"
    if ! AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" \
         AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
         aws "${endpoint_args[@]}" s3 cp "${ARTIFACT}" "${destino}"; then
      echo "[backup] ERROR: offsite upload failed for ${ARTIFACT} -> ${destino}" >&2
      exit 1
    fi
    echo "[backup] Uploaded: ${destino}"
  }

  s3_upload "s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/daily/${ARTIFACT_BASE}"

  # O mensal sobe quando AINDA NAO EXISTE mensal para a competencia corrente.
  # Deliberadamente NAO e "se hoje e dia 1": uma unica noite falha no dia 1
  # custaria o mes inteiro, em silencio, e so se descobriria um ano depois.
  # O `ls` e uma chamada Class B (barata; gratuita nos dois candidatos).
  COMPETENCIA="$(date -u +%Y%m)"
  MENSAL_EXISTENTE="$(AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY}" \
    AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY}" \
    aws "${endpoint_args[@]}" s3 ls \
      "s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/monthly/vitali_${COMPETENCIA}" 2>/dev/null | head -1 || true)"
  if [ -z "${MENSAL_EXISTENTE}" ]; then
    echo "[backup] Sem mensal para a competencia ${COMPETENCIA} — promovendo este artefato"
    s3_upload "s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/monthly/${ARTIFACT_BASE}"
  fi
fi

# ── Success metric (Prometheus textfile collector — VitaliBackupStale) ──────
# Written HERE, and only here: after pg_dump, encryption and the optional
# offsite upload have ALL already succeeded (every branch above that can fail
# does so via `exit 1` before this point) and BEFORE the non-essential local
# retention/prune step below — pruning old backups is housekeeping, not part
# of "did this backup succeed", so a prune bug must never suppress this
# metric. A metric written earlier (e.g. right after pg_dump) or on any
# failure path would tell the VitaliBackupStale alert "backup ok" while the
# backup did not actually complete — worse than no alert at all.
#
# ${BACKUP_DIR}/metrics matches --collector.textfile.directory=/backups/metrics
# on the node-exporter service (docker/observability alerts.yml + node-exporter
# in docker-compose.observability.yml), which mounts the SAME `backups` named
# volume this container writes into (read-only). BACKUP_DIR defaults to
# /backups in both docker-compose.staging.yml and docker-compose.prod.yml.
#
# Atomic write (.tmp + mv, same filesystem/volume so mv is a rename, not a
# copy) so the textfile collector — which polls this directory on its own
# schedule, independent of this script — never reads a half-written file.
METRICS_DIR="${BACKUP_DIR}/metrics"
mkdir -p "${METRICS_DIR}"
METRICS_FILE="${METRICS_DIR}/vitali_backup.prom"
METRICS_TMP="${METRICS_FILE}.tmp.$$"
{
  echo "# HELP vitali_backup_last_success_timestamp_seconds Unix timestamp of the last successful vitali backup."
  echo "# TYPE vitali_backup_last_success_timestamp_seconds gauge"
  echo "vitali_backup_last_success_timestamp_seconds $(date -u +%s)"
} > "${METRICS_TMP}"
mv -f "${METRICS_TMP}" "${METRICS_FILE}"
echo "[backup] Metric written: ${METRICS_FILE}"

# ── Local retention (delete dumps older than the KEEP_LAST most-recent) ─────
# Matches both .dump and .dump.gpg artifacts.
OLD_DUMPS="$(ls -1t "${BACKUP_DIR}"/vitali_*.dump "${BACKUP_DIR}"/vitali_*.dump.gpg 2>/dev/null | tail -n "+$((KEEP_LAST + 1))")"
if [ -n "${OLD_DUMPS}" ]; then
  echo "[backup] Pruning $(echo "${OLD_DUMPS}" | wc -l | tr -d ' ') old backup(s)…"
  echo "${OLD_DUMPS}" | xargs rm -v
fi

echo "[backup] Done — ${KEEP_LAST} most-recent backup(s) retained in ${BACKUP_DIR}"
