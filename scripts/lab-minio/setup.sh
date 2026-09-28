#!/usr/bin/env bash
# Sobe o MinIO e prepara o cenário da ordem 032 (só teste, sem dado real):
#   - bucket COM object lock (versionado), com o nome do bucket de produção;
#   - bucket SEM object lock, para provar que o backend recusa gravar nele;
#   - usuário "gravador" com a MESMA política que docs/ops/ manda aplicar na AWS.
# Pronto quando /tmp/pronto existe. Credenciais vêm do ambiente (aleatórias por
# recibo, geradas por scripts/pytest.sh).
set -euo pipefail
: "${MINIO_ROOT_USER:?}" "${MINIO_ROOT_PASSWORD:?}" "${COLD_WRITER_KEY:?}" "${COLD_WRITER_SECRET:?}"
BUCKET="${COLD_BUCKET:-vitali-auditlog-cold}"

minio server /data --address :9000 --console-address :9001 --quiet &
srv=$!

for _ in $(seq 1 60); do
  mc alias set lab http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && break
  sleep 1
done
mc mb --with-lock "lab/$BUCKET" >/dev/null
mc mb "lab/$BUCKET-sem-lock" >/dev/null
mc admin policy create lab auditlog-cold-writer /policy.json >/dev/null
mc admin user add lab "$COLD_WRITER_KEY" "$COLD_WRITER_SECRET" >/dev/null
mc admin policy attach lab auditlog-cold-writer --user "$COLD_WRITER_KEY" >/dev/null
touch /tmp/pronto
echo "minio pronto: $BUCKET (lock), $BUCKET-sem-lock, usuário gravador"
wait "$srv"
