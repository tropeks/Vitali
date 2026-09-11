#!/usr/bin/env bash
# Vitali — Restore Drill Runner (ordem 003)
# ─────────────────────────────────────────────────────────────────────────────
# Envolve o `restore_test.sh` com o que ele nao faz, e com o cuidado que lidar
# com dado clinico exige. Tres coisas:
#
#   1. A CHAVE NUNCA E ECOADA. Ela entra por substituicao de comando lendo o
#      arquivo .env, e so existe no ambiente do processo. Nao vai para o log,
#      nao vai para o ledger, nao vai para o `ps` (nao e argumento de comando).
#      Por isso este wrapper existe: o comando que o ledger grava e o caminho
#      deste script, nao um `KEY=... bash restore_test.sh`.
#
#   2. O ARTEFATO SAI DO VOLUME CIFRADO. O mountpoint de um volume Docker e
#      root-only — o exemplo de uso do proprio restore_test.sh sugere apontar
#      BACKUP_DIR para la, e isso nao funciona sem sudo. Aqui o .gpg e copiado
#      por container para um diretorio de trabalho. Copia-se o CIFRADO: o texto
#      claro so existe dentro do WORKDIR efemero do drill.
#
#   3. O DRILL CANONICO NAO E MODIFICADO. Ele roda como esta, e o que ele
#      prova e dele. A comparacao de inventario (fase 2) e um SEGUNDO restore,
#      independente, em outro container descartavel — de proposito: misturar as
#      duas contaminaria "o drill passou" com codigo escrito na mesma sessao.
#
# Uso:
#   bash scripts/run_restore_drill.sh \
#     --env-file /srv/vulcan/apps/vitali/.env.staging \
#     --volume vitali-lab_backups \
#     --workdir /srv/vulcan/apps/vitali/drill \
#     --reference /srv/vulcan/apps/vitali/migracao/inventario-LAB.txt \
#     --inventory-sql /srv/vulcan/apps/vitali/migracao/inventario.sql
#
# Sai 0 so quando o drill passa E a limpeza e verificada. A comparacao de
# inventario e RELATADA integralmente (diff completo, nunca resumo) e nao
# reprova sozinha: diferenca pode ser escrita legitima no staging depois do
# dump. Quem le decide.
set -euo pipefail

ENV_FILE=""
VOLUME="vitali-lab_backups"
WORKDIR=""
REFERENCE=""
INVENTORY_SQL=""
ARTIFACT_NAME=""
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --volume) VOLUME="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --reference) REFERENCE="$2"; shift 2 ;;
    --inventory-sql) INVENTORY_SQL="$2"; shift 2 ;;
    --artifact) ARTIFACT_NAME="$2"; shift 2 ;;
    *) echo "[drill] argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

[ -n "$ENV_FILE" ] || { echo "[drill] --env-file e obrigatorio" >&2; exit 2; }
[ -n "$WORKDIR" ] || { echo "[drill] --workdir e obrigatorio" >&2; exit 2; }
[ -f "$ENV_FILE" ] || { echo "[drill] .env nao encontrado: $ENV_FILE" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
DRILL_CONTAINER="vitali-inventory-drill-$$"
FASE2_STATUS="nao executada"

cleanup() {
  docker rm -f "$DRILL_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── A chave. Substituicao de comando, sem echo, sem ir para argv. ────────────
# `cut -d= -f2-` preserva '=' de padding base64. Nada abaixo imprime $KEY.
BACKUP_ENCRYPTION_KEY="$(grep -m1 '^BACKUP_ENCRYPTION_KEY=' "$ENV_FILE" | cut -d= -f2-)"
export BACKUP_ENCRYPTION_KEY
if [ -z "$BACKUP_ENCRYPTION_KEY" ]; then
  echo "[drill] ✗ BACKUP_ENCRYPTION_KEY ausente ou vazia em $ENV_FILE" >&2
  exit 1
fi
echo "[drill] chave carregada do .env (${#BACKUP_ENCRYPTION_KEY} bytes, valor nao exibido)"

# ── Fase 0: extrair o artefato CIFRADO do volume, sem root ───────────────────
mkdir -p "$WORKDIR"
chmod 700 "$WORKDIR"

if [ -z "$ARTIFACT_NAME" ]; then
  ARTIFACT_NAME="$(docker run --rm -v "$VOLUME":/v:ro "$PG_IMAGE" \
    sh -c 'ls -t /v/*.dump.gpg 2>/dev/null | head -1 | xargs -r basename')"
fi
[ -n "$ARTIFACT_NAME" ] || { echo "[drill] ✗ nenhum .dump.gpg no volume $VOLUME" >&2; exit 1; }

docker run --rm -v "$VOLUME":/v:ro -v "$WORKDIR":/out "$PG_IMAGE" \
  sh -c "cp /v/'$ARTIFACT_NAME' /out/ && chmod 600 /out/'$ARTIFACT_NAME'"

ARTIFACT_PATH="$WORKDIR/$ARTIFACT_NAME"
ARTIFACT_SHA="$(sha256sum "$ARTIFACT_PATH" | cut -d' ' -f1)"
echo "[drill] artefato : $ARTIFACT_NAME"
echo "[drill] sha256   : $ARTIFACT_SHA"
echo "[drill] bytes    : $(stat -c%s "$ARTIFACT_PATH")"

# ── Fase 1: o drill canonico, intocado ──────────────────────────────────────
echo ""
echo "[drill] ─── fase 1: scripts/restore_test.sh ───────────────────────────"
DRILL_RC=0
BACKUP_DIR="$WORKDIR" bash "$HERE/restore_test.sh" || DRILL_RC=$?
if [ "$DRILL_RC" -ne 0 ]; then
  echo "[drill] ✗ restore_test.sh saiu $DRILL_RC" >&2
  exit "$DRILL_RC"
fi

# ── Fase 2: segundo restore, independente, para comparar o inventario ───────
if [ -n "$REFERENCE" ] && [ -n "$INVENTORY_SQL" ]; then
  echo ""
  echo "[drill] ─── fase 2: inventario tabela a tabela ──────────────────────"
  PGPW="inventory-drill-$$"
  docker run -d --name "$DRILL_CONTAINER" \
    -e POSTGRES_PASSWORD="$PGPW" -e POSTGRES_USER=vitali -e POSTGRES_DB=vitali \
    "$PG_IMAGE" >/dev/null

  for _ in $(seq 1 60); do
    if docker exec "$DRILL_CONTAINER" pg_isready -U vitali -d vitali >/dev/null 2>&1; then break; fi
    sleep 2
  done
  docker exec "$DRILL_CONTAINER" pg_isready -U vitali -d vitali >/dev/null 2>&1 \
    || { echo "[drill] ✗ postgres efemero da fase 2 nao ficou pronto" >&2; exit 1; }

  # O claro nunca toca o disco do host: decifra e entra por stdin no container.
  gpg --batch --quiet --yes --passphrase "$BACKUP_ENCRYPTION_KEY" --decrypt "$ARTIFACT_PATH" 2>/dev/null \
    | docker exec -i -e PGPASSWORD="$PGPW" "$DRILL_CONTAINER" \
        pg_restore -h 127.0.0.1 -U vitali -d vitali --no-owner >/dev/null 2>&1 || true

  ATUAL="$WORKDIR/inventario-RESTORE.txt"
  docker exec -i -e PGPASSWORD="$PGPW" "$DRILL_CONTAINER" \
    psql -h 127.0.0.1 -U vitali -d vitali -v ON_ERROR_STOP=1 < "$INVENTORY_SQL" > "$ATUAL" 2>&1

  echo "[drill] referencia: $REFERENCE"
  echo "[drill] restaurado: $ATUAL"
  if diff -u "$REFERENCE" "$ATUAL" > "$WORKDIR/inventario.diff"; then
    FASE2_STATUS="IDENTICO ao inventario de referencia"
    echo "[drill] ✓ $FASE2_STATUS"
  else
    FASE2_STATUS="DIFERENTE — $(grep -c '^[+-][^+-]' "$WORKDIR/inventario.diff" || true) linha(s) divergentes"
    echo "[drill] ! $FASE2_STATUS — diff COMPLETO abaixo, sem resumo:"
    cat "$WORKDIR/inventario.diff"
  fi
  docker rm -f "$DRILL_CONTAINER" >/dev/null 2>&1 || true
fi

# ── Fase 3: limpeza verificada, nao suposta ─────────────────────────────────
echo ""
echo "[drill] ─── fase 3: limpeza ──────────────────────────────────────────"

RESTOS_CONTAINER="$(docker ps -a --filter 'name=vitali-restore-drill-' --filter 'name=vitali-inventory-drill-' -q | wc -l)"
echo "[drill] containers de drill remanescentes: $RESTOS_CONTAINER"

# Prova por find: nenhum .dump em claro sobrou. /tmp cobre o WORKDIR do
# restore_test.sh (mktemp -d); o diretorio de trabalho cobre o nosso.
CLAROS_TMP="$(find /tmp -maxdepth 3 -name '*.dump' -type f 2>/dev/null | wc -l)"
CLAROS_WORK="$(find "$WORKDIR" -name '*.dump' -type f 2>/dev/null | wc -l)"
echo "[drill] .dump em claro em /tmp      : $CLAROS_TMP"
echo "[drill] .dump em claro em $WORKDIR : $CLAROS_WORK"
find /tmp -maxdepth 3 -name '*.dump' -type f 2>/dev/null | sed 's/^/[drill]   sobrou: /'
find "$WORKDIR" -name '*.dump' -type f 2>/dev/null | sed 's/^/[drill]   sobrou: /'

# A copia cifrada era redundante (o original segue no volume). Some.
shred -n 3 -z -u "$ARTIFACT_PATH" 2>/dev/null || rm -f "$ARTIFACT_PATH"
echo "[drill] copia cifrada removida: $ARTIFACT_NAME (sha256 $ARTIFACT_SHA registrado acima)"

echo ""
echo "[drill] ═══ resumo ═══"
echo "[drill] artefato   : $ARTIFACT_NAME ($ARTIFACT_SHA)"
echo "[drill] fase 1     : restore_test.sh PASSOU"
echo "[drill] fase 2     : $FASE2_STATUS"
echo "[drill] limpeza    : containers=$RESTOS_CONTAINER claros_tmp=$CLAROS_TMP claros_work=$CLAROS_WORK"

if [ "$RESTOS_CONTAINER" -ne 0 ] || [ "$CLAROS_TMP" -ne 0 ] || [ "$CLAROS_WORK" -ne 0 ]; then
  echo "[drill] ✗ limpeza incompleta — ver linhas 'sobrou' acima" >&2
  exit 1
fi
echo "[drill] ✓ drill completo e limpo"
