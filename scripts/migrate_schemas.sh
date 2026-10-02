#!/usr/bin/env bash
# scripts/migrate_schemas.sh — migra todos os schemas; idempotente.
#
# Cada passo roda num contêiner DESCARTÁVEL da imagem que o compose aponta
# (`compose run --rm --no-deps django`), nunca por `exec` (ordem 035). `exec` entra no
# contêiner que está no ar: num deploy, a release ANTERIOR, que não conhece as
# migrations novas. O scripts/deploy.sh chama este script antes do `up`, com a
# IMAGE_TAG nova; postgres tem de estar no ar.
#
# Compose: se COMPOSE_FILE estiver definido, usa as mesmas variáveis do deploy.sh e do
# smoke_test.sh (COMPOSE_FILE com ':', COMPOSE_PROJECT_NAME, COMPOSE_ENV_FILE). Sem ele,
# o compose de dev da raiz, como antes.

set -euo pipefail

compose_cmd=(docker compose)
if [[ -n "${COMPOSE_FILE:-}" ]]; then
    IFS=':' read -r -a _compose_files <<< "$COMPOSE_FILE"
    for _f in "${_compose_files[@]}"; do
        compose_cmd+=(-f "$_f")
    done
    if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
        compose_cmd+=(-p "$COMPOSE_PROJECT_NAME")
    fi
    if [[ -n "${COMPOSE_ENV_FILE:-}" ]]; then
        export STAGING_ENV_FILE="$COMPOSE_ENV_FILE"
        compose_cmd+=(--env-file "$COMPOSE_ENV_FILE")
    fi
elif [ -f "docker-compose.override.yml" ]; then
    compose_cmd+=(-f docker-compose.yml -f docker-compose.override.yml)
elif [ -f "docker-compose.prod.yml" ]; then
    compose_cmd+=(-f docker-compose.yml -f docker-compose.prod.yml)
else
    compose_cmd+=(-f docker-compose.yml)
fi
manage=("${compose_cmd[@]}" run --rm --no-deps -T django python manage.py)

# Shared primeiro: o public guarda o registro de tenants. Falha aqui bloqueia tudo.
echo "Migrating public schema..."
"${manage[@]}" migrate_schemas --shared --noinput

echo "Migrating all tenant schemas..."
"${manage[@]}" migrate_schemas --tenant --noinput

echo "All schemas migrated successfully."

# Ordem 021, Emenda do Imediato: "não carimbo 20 anos em cima de expurgo
# inerte". A 020 entregou ensure_month_partition/ensure_tenant_partition sem
# ninguém os chamar no caminho real — toda escrita caía na DEFAULT, e o
# expurgo por tenant nunca tinha o que derrubar. Isto é O ENTRYPOINT depois
# do migrate (o Celery Beat diário cobre o mês virando sem deploy no meio —
# ver apps.core.tasks.ensure_audit_partitions).
echo "Ensuring core_auditlog partitions for the current and next month..."
# Ordem 038. Banco com trilha anterior à 0043: as linhas legadas estão na folha DEFAULT, e
# o ensure recusa criar a folha dedicada do mês por cima delas (sai com erro, nomeando os
# tenants). O remédio é o backfill, que move as linhas por grupo (uma transação por mês e
# tenant) e é idempotente. Depois do backfill o ensure roda de novo; se falhar outra vez, a
# causa não era a DEFAULT e o `set -e` aborta o deploy antes do `up`. Sem falha, nada disso
# roda.
#
# O backfill automático é DESLIGADO por padrão (DEPLOY_AUTO_BACKFILL=1 liga). O ADR-0001 trata
# rodar o backfill em staging ou produção como decisão operacional posterior, a medir antes
# e fora do pico, e o backfill desliga o trigger da tabela por grupo: as escritas de auditoria
# da release ainda no ar esperam. Até o Capitão emendar o ADR, o deploy só avisa e aborta.
if ! "${manage[@]}" ensure_audit_partitions; then
    if [[ "${DEPLOY_AUTO_BACKFILL:-0}" != "1" ]]; then
        echo "ensure_audit_partitions falhou (a causa está na saída acima)." >&2
        echo "Se for linha de trilha antiga na folha DEFAULT: rode backfill_audit_partitions (dry-run)" >&2
        echo "para medir, depois --execute fora do pico (ADR-0001), e repita o deploy." >&2
        echo "O backfill automático está desligado; DEPLOY_AUTO_BACKFILL=1 o liga." >&2
        exit 1
    fi
    echo "ensure_audit_partitions falhou (a causa está na saída acima). Se for linha de trilha" >&2
    echo "antiga na folha DEFAULT, o backfill resolve; se não for, o ensure falha de novo." >&2
    echo "Contagem do que será movido (dry-run, fica no log do deploy)..."
    "${manage[@]}" backfill_audit_partitions
    echo "Movendo as linhas com backfill_audit_partitions --execute..."
    "${manage[@]}" backfill_audit_partitions --execute
    echo "Repetindo ensure_audit_partitions depois do backfill..."
    "${manage[@]}" ensure_audit_partitions
fi
