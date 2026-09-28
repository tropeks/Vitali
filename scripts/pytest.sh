#!/usr/bin/env bash
# Roda o pytest do backend do Vitali NA LAB, contra o código do checkout (ordem 027).
#
# Por que na lab: a forge não roda compose do Vitali (regra do Imediato, 17/09/2026).
# Porta publicada por Docker passa por fora do firewall dela, e ela guarda segredos
# que não são do Vitali. Este wrapper nunca fala com o daemon local: todo comando
# docker vai com `--context lab`, e DOCKER_HOST/DOCKER_CONTEXT são descartados.
#
# O que ele faz (a receita de docs/DEVELOPMENT.md §Running tests, executável):
#   1. imagem de teste vitali-test:x com INSTALL_DEV=true, a partir de ./backend;
#   2. overlay vitali-test:x-full com scripts/ em /scripts (o test_drill_metric
#      executa /scripts/drill_metric.sh) e os arquivos de compose de dev na raiz
#      (a guarda test_compose_exposure os lê);
#   3. contêiner efêmero com --name único, na rede $LAB_NETWORK (padrão v018net:
#      postgres e redis sem porta publicada), COVERAGE_FILE=/tmp/.coverage.
#
# Uso:  scripts/pytest.sh [alvo e flags do pytest]      (sem alvo: a suíte inteira)
#       scripts/pytest.sh apps/core/tests/test_auth.py -x
#       PYTEST_NO_BUILD=1 scripts/pytest.sh ...        (reusa as imagens já construídas)
#       PYTEST_CMD="ruff check apps/ vitali/" scripts/pytest.sh   (outro comando na imagem)
#       PYTEST_MINIO=1 scripts/pytest.sh ...           (com o MinIO efêmero da ordem 032)
#
# PYTEST_MINIO=1 (ordem 032; autorização do Diretor de 27/09/2026: só teste, sem
# dado real, derrubado ao fim de cada recibo): sobe um MinIO na mesma rede, SEM
# porta publicada, com credenciais aleatórias deste recibo e a política de
# docs/ops/auditlog-cold-writer-policy.json no usuário gravador; passa o endpoint
# ao pytest (apps/core/tests/test_cold_storage_minio.py) e o derruba na saída,
# com qualquer código de saída, conferindo que sumiu.
set -euo pipefail

unset DOCKER_HOST DOCKER_CONTEXT
LAB_NETWORK="${LAB_NETWORK:-v018net}"

self="$(readlink -f "${BASH_SOURCE[0]}")"
repo="$(cd "$(dirname "$self")/.." && pwd)"
cd "$repo"
[ -d backend ] || { echo "erro: não achei backend/ em $repo" >&2; exit 1; }

# A sessão pode ser anterior à entrada no grupo docker: reexecuta sob `sg docker`.
if ! docker --context lab version >/dev/null 2>&1; then
  if [ -z "${_VITALI_PYTEST_SG:-}" ] && command -v sg >/dev/null; then
    export _VITALI_PYTEST_SG=1
    exec sg docker -c "$(printf '%q ' "$self" "$@")"
  fi
  echo "erro: o contexto docker 'lab' não responde (docker --context lab version)." >&2
  exit 1
fi
lab() { docker --context lab "$@"; }

lab network inspect "$LAB_NETWORK" >/dev/null 2>&1 || {
  echo "erro: a rede $LAB_NETWORK não existe na lab (postgres e redis sem porta publicada)." >&2
  exit 1
}

if [ "${PYTEST_NO_BUILD:-0}" != "1" ]; then
  lab build -q --build-arg INSTALL_DEV=true -t vitali-test:x ./backend >/dev/null
  # O contexto só serve ao build: sai antes do `exec` final, que não dispara trap EXIT.
  ctx="$(mktemp -d)"
  trap 'rm -rf "$ctx"' EXIT
  cp -r scripts "$ctx/scripts"
  cp docker-compose.yml docker-compose.override.yml "$ctx/"
  printf '%s\n' 'FROM vitali-test:x' 'COPY scripts /scripts' \
    'COPY docker-compose.yml docker-compose.override.yml /' > "$ctx/Dockerfile"
  lab build -q -t vitali-test:x-full "$ctx" >/dev/null
  rm -rf "$ctx"
  trap - EXIT
fi

name="vpytest-$(date +%Y%m%d%H%M%S)-$$"
echo "lab: contêiner $name na rede $LAB_NETWORK (docker --context lab ps -a --filter name=$name)" >&2

if [ -n "${PYTEST_CMD:-}" ]; then
  # shellcheck disable=SC2086 # PYTEST_CMD é uma linha de comando, dividida de propósito
  set -- ${PYTEST_CMD}
else
  set -- pytest "$@" -q --no-header -p no:cacheprovider
fi

minio_env=()
if [ "${PYTEST_MINIO:-0}" = "1" ]; then
  minio_img="vitali-minio-test:2025-09-07"
  if [ "${PYTEST_NO_BUILD:-0}" != "1" ] || ! lab image inspect "$minio_img" >/dev/null 2>&1; then
    mctx="$(mktemp -d)"
    cp scripts/lab-minio/Dockerfile scripts/lab-minio/setup.sh \
      docs/ops/auditlog-cold-writer-policy.json "$mctx/"
    lab build -q -t "$minio_img" "$mctx" >/dev/null
    rm -rf "$mctx"
  fi
  rnd() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
  minio_name="vminio-${name#vpytest-}"
  root_key="root$(rnd | head -c 12)"; root_secret="$(rnd)"
  writer_key="gravador$(rnd | head -c 12)"; writer_secret="$(rnd)"
  derruba_minio() {
    lab rm -f "$minio_name" >/dev/null 2>&1 || true
    if lab ps -a --filter "name=$minio_name" --format '{{.Names}}' | grep -q .; then
      echo "ERRO: o MinIO $minio_name continua na lab depois do recibo" >&2
      return 1
    fi
    echo "lab: MinIO $minio_name derrubado (docker --context lab ps -a não o lista)" >&2
  }
  trap derruba_minio EXIT
  lab run -d --rm --name "$minio_name" --network "$LAB_NETWORK" \
    -e MINIO_ROOT_USER="$root_key" -e MINIO_ROOT_PASSWORD="$root_secret" \
    -e COLD_WRITER_KEY="$writer_key" -e COLD_WRITER_SECRET="$writer_secret" \
    "$minio_img" >/dev/null
  for _ in $(seq 1 60); do
    lab exec "$minio_name" test -f /tmp/pronto 2>/dev/null && break
    sleep 1
  done
  lab exec "$minio_name" test -f /tmp/pronto || {
    echo "erro: o MinIO $minio_name não ficou pronto em 60 s" >&2
    lab logs "$minio_name" >&2 || true
    exit 1
  }
  echo "lab: MinIO $minio_name na rede $LAB_NETWORK, sem porta publicada" >&2
  minio_env=(
    -e AUDIT_LOG_COLD_S3_TEST_ENDPOINT="http://$minio_name:9000"
    -e AUDIT_LOG_COLD_S3_TEST_ROOT_KEY="$root_key"
    -e AUDIT_LOG_COLD_S3_TEST_ROOT_SECRET="$root_secret"
    -e AUDIT_LOG_COLD_S3_TEST_WRITER_KEY="$writer_key"
    -e AUDIT_LOG_COLD_S3_TEST_WRITER_SECRET="$writer_secret"
  )
fi

run=(docker --context lab run --rm --name "$name" --network "$LAB_NETWORK"
  -e DJANGO_SETTINGS_MODULE=vitali.settings.development
  -e DATABASE_URL=postgres://vitali:vitali@postgres:5432/vitali
  -e REDIS_URL=redis://redis:6379/0
  -e COVERAGE_FILE=/tmp/.coverage
  "${minio_env[@]}"
  vitali-test:x-full "$@")

if [ "${PYTEST_MINIO:-0}" != "1" ]; then
  exec "${run[@]}"
fi
# Sem exec: o trap EXIT tem de rodar depois do pytest para derrubar o MinIO.
# O pytest vai em segundo plano com `wait`: o bash só atende um sinal quando o
# filho em primeiro plano termina, e o `docker run` não repassa o SIGTERM. Com
# `wait`, um recibo interrompido (kill, Ctrl-C) derruba o pytest e o MinIO na hora.
trap 'lab rm -f "$name" >/dev/null 2>&1; exit 130' INT TERM HUP
status=0
"${run[@]}" &
wait "$!" || status=$?
trap - INT TERM HUP
derruba_minio || status=1
trap - EXIT
exit "$status"
