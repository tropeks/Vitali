#!/usr/bin/env bash
# scripts/deploy.sh — a ordem de um deploy do Vitali (ordem 035).
#
# Uso (a linha inteira está em docs/DEPLOY.md §Release Pipeline): as variáveis abaixo
# e `bash scripts/deploy.sh`.
#
# 1. pull das imagens da release nova;
# 2. postgres e redis no ar (não mexe no código que está servindo);
# 3. scripts/migrate_schemas.sh: shared, tenant e partições da trilha, cada um num
#    contêiner DESCARTÁVEL da imagem nova (`compose run --rm`), com a release
#    anterior ainda servindo;
# 4. só então `up -d --wait`: o código novo sobe contra um schema que já o espera,
#    e o script só termina quando o healthcheck responde.
#
# Por que nesta ordem: migration de tenant é aditiva (docs/TENANT_MIGRATIONS.md, fase 1
# de 2) justamente para que a release ANTERIOR rode contra o schema novo. O contrário
# não vale: com `up` antes do migrate, todo AddField de tenant abria uma janela em que o
# código novo consultava uma coluna inexistente (na 033, o portal inteiro de um tenant
# ainda não migrado responderia 500).
#
# Se a migração falhar (o tenant 47 de 200), o script para ANTES do `up`: a release
# anterior continua no ar, contra os schemas migrados e os não migrados. Corrija e rode
# de novo; migrate_schemas é idempotente.
#
# Variáveis (as mesmas do scripts/smoke_test.sh):
#   IMAGE_TAG, GHCR_REPO   — a release nova, lidas pelo arquivo de compose
#   COMPOSE_PROJECT_NAME   — projeto do compose (staging: vitali-staging)
#   COMPOSE_FILE           — arquivo(s) de compose, separados por ':'
#   COMPOSE_ENV_FILE       — env file do compose (staging: .env.staging)
#   DEPLOY_PULL=0          — não faz pull (imagem construída no próprio host, como na
#                            prova da lab); o padrão é fazer
#   DEPLOY_SERVICES        — serviços do `up` final, separados por espaço; vazio = todos
#
# O smoke continua passo próprio, depois deste script (docs/DEPLOY.md).
set -euo pipefail

self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${COMPOSE_FILE:?defina COMPOSE_FILE (ex.: docker-compose.staging.yml)}"
: "${IMAGE_TAG:?defina IMAGE_TAG (ex.: sha-<commit>): o deploy precisa saber qual release sobe}"
export COMPOSE_FILE IMAGE_TAG

IFS=':' read -r -a _compose_files <<< "$COMPOSE_FILE"
compose_cmd=(docker compose)
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

if [[ "${DEPLOY_PULL:-1}" != "0" ]]; then
  echo "deploy: pull da release ${IMAGE_TAG}..."
  "${compose_cmd[@]}" pull
fi

echo "deploy: postgres e redis no ar (o código que está servindo não é tocado)..."
"${compose_cmd[@]}" up -d --wait postgres redis

echo "deploy: migrando com a imagem nova, antes de subir o código novo..."
bash "$self_dir/migrate_schemas.sh"

read -r -a _services <<< "${DEPLOY_SERVICES:-}"
echo "deploy: schema pronto; subindo a release ${IMAGE_TAG}..."
"${compose_cmd[@]}" up -d --wait "${_services[@]}"
echo "deploy: release ${IMAGE_TAG} no ar e saudável. Rode o scripts/smoke_test.sh."
