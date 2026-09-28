#!/usr/bin/env bash
# Prova da ordem 035 NA LAB: o scripts/deploy.sh migra com a imagem nova antes de
# subir o código, e nenhum request vê a janela do schema velho.
#
# O caminho real: o docker-compose.staging.yml de verdade, as imagens de produção
# (Dockerfile sem INSTALL_DEV) do par real da ordem 033, e o deploy pelo mesmo
# script que o docs/DEPLOY.md manda rodar. A 0004 da 033 adiciona
# invite_token_hash, que a lista de convites do portal lê em todo request.
#   PROVA_ANTERIOR (padrão 7dd140c, aceite da 032) — a release que está no ar
#   PROVA_NOVA     (padrão 62223b3, aceite da 033) — a release que sobe
#
# Dois projetos efêmeros, um depois do outro, cada um do zero:
#   prova035a (controle): a ordem antiga, `up` do código novo antes do migrate. A
#     sonda tem de ver 5xx; se não vir, ela não enxerga o defeito e a parte B não
#     provaria nada. Depois do migrate, tudo 200.
#   prova035b (a prova): a sonda bate a cada 0,2 s durante o scripts/deploy.sh
#     inteiro. analise.py cruza as amostras com os eventos do docker: nenhum 5xx;
#     a release anterior serve 200 contra o schema já migrado; a nova, depois de
#     saudável. Depois, o paciente ativa pela API, na release nova, o convite que
#     a release anterior gravou em claro, e o banco tem o hash e não tem o claro.
#
# Limites (INTENT §Limites e regra do Imediato de 17/09): todo comando docker vai
# para o contexto `lab`, nunca para o daemon da forge; nenhuma porta publicada
# (nginx, orthanc e o resto nem sobem, e o overlay zera as portas deles mesmo
# assim); segredos aleatórios deste recibo, dado de teste só; tudo derrubado com
# `down -v` na saída, com qualquer código, conferindo que sumiu.
#
# Uso: scripts/lab-deploy-prova/prova.sh
#      (recibo: maestro evidence --record --label order-35-prova -- scripts/lab-deploy-prova/prova.sh)
set -euo pipefail
shopt -s inherit_errexit  # falha dentro de $(...) aborta a prova, não segue calada

unset DOCKER_HOST
export DOCKER_CONTEXT=lab
aqui="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
repo="$(cd "$aqui/../.." && pwd)"
cd "$repo"

# A sessão pode ser anterior à entrada no grupo docker: reexecuta sob `sg docker`.
if ! docker version >/dev/null 2>&1; then
  if [ -z "${_PROVA035_SG:-}" ] && command -v sg >/dev/null; then
    export _PROVA035_SG=1
    exec sg docker -c "$(printf '%q ' "$aqui/prova.sh" "$@")"
  fi
  echo "erro: o contexto docker 'lab' não responde." >&2
  exit 1
fi
[ "$(docker context show)" = "lab" ] || { echo "erro: contexto docker não é a lab" >&2; exit 1; }

ANTERIOR="${PROVA_ANTERIOR:-7dd140c}"
NOVA="${PROVA_NOVA:-62223b3}"
export GHCR_REPO=prova035
SERVICOS="django celery-worker celery-beat"
tmp="$(mktemp -d)"

# Derruba por rótulo, sem depender do env file nem do overlay (que podem nem existir
# ainda, ou já ter sumido): contêineres, volumes e rede de cada projeto da prova.
limpa() {
  local status=$? p resto=0 ids
  for p in prova035a prova035b; do
    docker rm -f "$p-sonda" >/dev/null 2>&1 || true
    ids="$(docker ps -aq --filter "label=com.docker.compose.project=$p")"
    [ -z "$ids" ] || docker rm -f $ids >/dev/null 2>&1 || true
    ids="$(docker volume ls -q --filter "label=com.docker.compose.project=$p")"
    [ -z "$ids" ] || docker volume rm $ids >/dev/null 2>&1 || true
    docker network rm "${p}_default" >/dev/null 2>&1 || true
    if docker ps -aq --filter "label=com.docker.compose.project=$p" | grep -q . ||
      docker volume ls -q --filter "label=com.docker.compose.project=$p" | grep -q .; then
      echo "ERRO: o projeto $p deixou contêiner ou volume na lab" >&2
      resto=1
    fi
  done
  [ "$resto" = 1 ] || echo "lab: projetos prova035a e prova035b derrubados (nenhum contêiner nem volume)" >&2
  rm -rf "$tmp"
  [ "$resto" = 0 ] || status=1
  exit "$status"
}
trap limpa EXIT
trap 'exit 130' INT TERM HUP

# STAGING_ENV_FILE é o env_file dos serviços da aplicação no docker-compose.staging.yml;
# sem ele, o padrão é `.env.staging` da raiz, que na máquina de quem roda pode ser um
# arquivo de segredos de verdade. Aqui ele é sempre o env efêmero desta prova.
export STAGING_ENV_FILE="$tmp/env"
compose() {
  local p="$1"; shift
  docker compose -p "$p" -f docker-compose.staging.yml -f "$tmp/prova.yml" \
    --env-file "$tmp/env" "$@"
}
img() { echo "ghcr.io/$GHCR_REPO/vitali-backend:$1"; }
rnd() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
campo() { python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$1" "$2"; }

echo "== imagens de produção: anterior=$ANTERIOR nova=$NOVA"
for par in "anterior $ANTERIOR" "nova $NOVA"; do
  set -- $par
  git archive --format=tar "$2:backend" | docker build -q -t "$(img "$1")" - >/dev/null
done

# Segredos deste recibo. As chaves passam pelos validadores de production.py.
pg="$(rnd)"; redis="$(rnd)"
fernet="$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
cat > "$tmp/env" <<EOF
SECRET_KEY=$(rnd)$(rnd)
ENVIRONMENT=staging
DEBUG=False
ALLOWED_HOSTS=prova.local,prova-publico.local,localhost
CSRF_TRUSTED_ORIGINS=https://prova.local
HEALTHCHECK_HOST=prova-publico.local
POSTGRES_DB=vitali
POSTGRES_USER=vitali
POSTGRES_PASSWORD=$pg
DATABASE_URL=postgres://vitali:$pg@postgres:5432/vitali
REDIS_PASSWORD=$redis
REDIS_URL=redis://:$redis@redis:6379/0
FIELD_ENCRYPTION_KEY=$fernet
BACKUP_ENCRYPTION_KEY=$(rnd)
ORTHANC_AUTH_HEADER=Basic $(rnd)
ORTHANC_USERNAME=prova
ORTHANC_PASSWORD=$(rnd)
ORTHANC_WEBHOOK_SECRET=$(rnd)
WHATSAPP_EVOLUTION_API_KEY=$(rnd)
WHATSAPP_WEBHOOK_SECRET=$(rnd)
EOF

# Overlay da lab: o init.sql do postgres vai por conteúdo, não por bind mount (o
# caminho da forge não existe no host da lab); apparmor como no docker-compose.lab.yml;
# portas zeradas nos serviços que publicam, embora eles não subam aqui.
{
  printf '%s\n' 'services:' '  postgres:' '    security_opt: !override []' \
    '    volumes: !override' '      - postgres_data:/var/lib/postgresql/data' \
    '    configs:' '      - source: prova_pg_init' \
    '        target: /docker-entrypoint-initdb.d/init.sql' \
    '  nginx:' '    ports: !reset []' '  orthanc:' '    ports: !reset []' \
    'configs:' '  prova_pg_init:' '    content: |'
  sed -e 's/\$/$$/g' -e 's/^/      /' docker/postgres/init.sql
} > "$tmp/prova.yml"

# Nenhum serviço pode ler env_file fora do diretório efêmero desta prova.
fora="$(IMAGE_TAG=anterior compose prova035a config --format json |
  python3 -c 'import json,sys; t=sys.argv[1]; c=json.load(sys.stdin)
print(" ".join(f"{n}:{e['"'"'path'"'"']}" for n,s in c["services"].items() for e in s.get("env_file") or [] if not e["path"].startswith(t)))' "$tmp")"
[ -z "$fora" ] || { echo "erro: env_file fora da prova: $fora" >&2; exit 1; }

deploy_env() {
  env COMPOSE_PROJECT_NAME="$1" COMPOSE_FILE="docker-compose.staging.yml:$tmp/prova.yml" \
    COMPOSE_ENV_FILE="$tmp/env" IMAGE_TAG="$2" DEPLOY_PULL=0 DEPLOY_SERVICES="$SERVICOS" "${@:3}"
}

# A primeira subida de um ambiente, pelo quickstart do DEPLOY.md: banco, schema e
# bootstrap com a imagem que vai servir, e então o deploy.sh (o healthcheck pede
# /readiness/ no HEALTHCHECK_HOST, que só existe depois do bootstrap).
# Progresso vai para stderr; stdout é só a linha de dados do prepara.py.
sobe_anterior() {
  local p="$1"
  echo "== $p: release anterior no ar" >&2
  IMAGE_TAG=anterior compose "$p" up -d --wait postgres redis >&2
  deploy_env "$p" anterior bash scripts/migrate_schemas.sh >/dev/null
  IMAGE_TAG=anterior BOOTSTRAP_ADMIN_PASSWORD="$(rnd)" compose "$p" run --rm --no-deps -T \
    -e BOOTSTRAP_ADMIN_PASSWORD django python manage.py bootstrap_beta \
    --public-domain prova-publico.local --clinic-slug prova --clinic-domain prova.local \
    --admin-email admin@prova.local >/dev/null
  deploy_env "$p" anterior bash scripts/deploy.sh >&2
  IMAGE_TAG=anterior compose "$p" run --rm --no-deps -T django python manage.py shell \
    < "$aqui/prepara.py" | sed -n 's/^PROVA035 //p'
}

sonda() {  # sonda <projeto> <token> [VAR=valor...] — contêiner na rede do projeto
  local p="$1" token="$2"; shift 2
  local extra=() kv
  for kv in "$@"; do extra+=(-e "$kv"); done
  docker run --name "$p-sonda" --network "${p}_default" \
    -e SONDA_HOST=prova.local -e SONDA_TOKEN="$token" "${extra[@]}" \
    -e SONDA_B64="$(base64 -w0 "$aqui/sonda.py")" "$(img anterior)" \
    python -c 'import base64,os; exec(base64.b64decode(os.environ["SONDA_B64"]))'
}
sonda_por() {  # sonda_por <projeto> <token> <segundos> <arquivo>
  sonda "$1" "$2" >/dev/null 2>&1 &
  sleep "$3"
  docker stop -t 5 "$1-sonda" >/dev/null
  wait || true
  docker logs "$1-sonda" > "$4" 2>/dev/null
  docker rm -f "$1-sonda" >/dev/null
}

# ── A: controle, a ordem antiga ──────────────────────────────────────────────
dados="$(sobe_anterior prova035a)"
echo "== prova035a: ordem antiga, código novo no ar ANTES do migrate"
IMAGE_TAG=nova compose prova035a up -d --wait $SERVICOS
sonda_por prova035a "$(campo "$dados" admin_token)" 6 "$tmp/a-quebra.jsonl"
python3 "$aqui/analise.py" quebra "$tmp/a-quebra.jsonl"
deploy_env prova035a nova bash scripts/migrate_schemas.sh >/dev/null
sonda_por prova035a "$(campo "$dados" admin_token)" 4 "$tmp/a-depois.jsonl"
python3 "$aqui/analise.py" tudo200 "$tmp/a-depois.jsonl"
compose prova035a down -v --remove-orphans >/dev/null 2>&1

# ── B: a prova, o scripts/deploy.sh ─────────────────────────────────────────
dados="$(sobe_anterior prova035b)"
echo "== prova035b: scripts/deploy.sh da release nova, com a sonda ligada"
# Eventos AO VIVO desde antes do deploy: o daemon guarda pouco histórico, e os
# healthchecks o enchem; consultar o passado com --since volta vazio.
docker events --format '{{json .}}' --filter type=container \
  --filter "label=com.docker.compose.project=prova035b" > "$tmp/b-eventos.jsonl" &
eventos_pid=$!
sonda prova035b "$(campo "$dados" admin_token)" >/dev/null 2>&1 &
sonda_pid=$!
sleep 3
deploy_env prova035b nova bash scripts/deploy.sh
sleep 3
docker stop -t 5 prova035b-sonda >/dev/null
wait "$sonda_pid" || true
kill "$eventos_pid" && wait "$eventos_pid" || true
docker logs prova035b-sonda > "$tmp/b-sonda.jsonl" 2>/dev/null
docker rm -f prova035b-sonda >/dev/null
python3 "$aqui/analise.py" deploy "$tmp/b-sonda.jsonl" "$tmp/b-eventos.jsonl"

echo "== prova035b: o convite gravado pela release anterior ativa na nova"
ativacao="$(sonda prova035b "$(campo "$dados" paciente_token)" SONDA_MODO=ativa \
  SONDA_CONVITE="$(campo "$dados" convite_token)")"
docker rm -f prova035b-sonda >/dev/null
echo "  ativação: $(campo "$ativacao" s)"
[ "$(campo "$ativacao" s)" = 200 ] || { echo "FALHA: ativação: $ativacao" >&2; exit 1; }
veredito="$(IMAGE_TAG=nova compose prova035b run --rm --no-deps -T \
  -e PROVA_SCHEMA="$(campo "$dados" schema)" -e PROVA_CONVITE_ID="$(campo "$dados" convite_id)" \
  -e PROVA_CONVITE_TOKEN="$(campo "$dados" convite_token)" \
  django python manage.py shell < "$aqui/confere.py" | sed -n 's/^PROVA035 //p')"
echo "  banco: $veredito"
[ "$(campo "$veredito" hash_confere)" = True ] && [ "$(campo "$veredito" claro_apagado)" = True ] ||
  { echo "FALHA: convite no banco: $veredito" >&2; exit 1; }

echo "== PROVA 035 OK: a ordem antiga quebra (controle), a do deploy.sh não."
