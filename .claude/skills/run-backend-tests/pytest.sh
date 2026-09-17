#!/usr/bin/env bash
# Roda pytest do backend do Vitali contra o CÓDIGO DO CHECKOUT.
#
# Por que não `docker compose exec django pytest`: o container vitali-django-1 usa
# imagem baked e não tem o bind ./backend:/app ativo — o pytest de lá roda código
# velho e dá falso-verde. Aqui sobe um container efêmero da imagem de dev
# (vitali-django, a única com pytest) montando o backend do checkout em /app.
#
# Uso:  scripts/pytest.sh [alvo e flags do pytest]
#       scripts/pytest.sh apps/pharmacy/tests/test_stockout_checker.py -x
#       PYTEST_CREATE_DB=1 scripts/pytest.sh apps/billing   # depois de mexer em migration
set -euo pipefail

# readlink -f resolve o symlink scripts/pytest.sh -> .claude/skills/.../pytest.sh,
# senão o cálculo do repo sobe a partir de scripts/ e aponta para fora do checkout.
self="$(readlink -f "${BASH_SOURCE[0]}")"
repo="$(cd "$(dirname "$self")/../../.." && pwd)"
cd "$repo"
[ -d backend ] || { echo "erro: rode a partir do checkout do Vitali (não achei backend/ em $repo)" >&2; exit 1; }

db_flag="--reuse-db"
[ "${PYTEST_CREATE_DB:-0}" = "1" ] && db_flag="--create-db"

extra=()
[ "${PYTEST_AS_ROOT:-0}" = "1" ] && extra+=(-u root)   # necessário só para makemigrations

exec sudo -n docker run --rm --network vitali_default \
  -e DJANGO_SETTINGS_MODULE=vitali.settings.development \
  -e DATABASE_URL=postgres://vitali:vitali@postgres:5432/vitali \
  -e REDIS_URL=redis://redis:6379/0 \
  -v "$repo/backend:/app" "${extra[@]}" vitali-django \
  pytest "$@" -q --no-cov "$db_flag" -p no:cacheprovider
