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
  ctx="$(mktemp -d)"
  trap 'rm -rf "$ctx"' EXIT
  cp -r scripts "$ctx/scripts"
  cp docker-compose.yml docker-compose.override.yml "$ctx/"
  printf '%s\n' 'FROM vitali-test:x' 'COPY scripts /scripts' \
    'COPY docker-compose.yml docker-compose.override.yml /' > "$ctx/Dockerfile"
  lab build -q -t vitali-test:x-full "$ctx" >/dev/null
fi

name="vpytest-$(date +%Y%m%d%H%M%S)-$$"
echo "lab: contêiner $name na rede $LAB_NETWORK (docker --context lab ps -a --filter name=$name)" >&2

if [ -n "${PYTEST_CMD:-}" ]; then
  # shellcheck disable=SC2086 # PYTEST_CMD é uma linha de comando, dividida de propósito
  set -- ${PYTEST_CMD}
else
  set -- pytest "$@" -q --no-header -p no:cacheprovider
fi

exec docker --context lab run --rm --name "$name" --network "$LAB_NETWORK" \
  -e DJANGO_SETTINGS_MODULE=vitali.settings.development \
  -e DATABASE_URL=postgres://vitali:vitali@postgres:5432/vitali \
  -e REDIS_URL=redis://redis:6379/0 \
  -e COVERAGE_FILE=/tmp/.coverage \
  vitali-test:x-full "$@"
