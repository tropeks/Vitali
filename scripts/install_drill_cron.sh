#!/usr/bin/env bash
# Vitali — instala o drill de restore noturno no crontab do HOST (ordem 011)
# ─────────────────────────────────────────────────────────────────────────────
# POR QUE NO HOST, e não como serviço no compose. O drill sobe contêineres
# descartáveis (um postgres por fase). Um serviço que faz isso precisa do socket
# do Docker montado dentro dele — e o socket do Docker é root no host: quem o
# alcança, alcança tudo. Trocar isso por uma linha de cron seria vender o
# perímetro para economizar configuração.
#
# Idempotente: reescreve a própria linha, marcada por MARCA, sem tocar nas
# outras entradas do crontab. Imprime o que instalou, porque instalação que não
# mostra o resultado é instalação que ninguém confere.
#
# Uso:
#   bash scripts/install_drill_cron.sh \
#     --app-dir /srv/vulcan/apps/vitali \
#     --volume vitali-lab_backups \
#     [--hora 3] [--remover]
set -euo pipefail

MARCA="# vitali-restore-drill (ordem 011) — nao editar a mao; use scripts/install_drill_cron.sh"
APP_DIR=""
VOLUME="vitali-lab_backups"
HORA="3"
REMOVER=0

while [ $# -gt 0 ]; do
  case "$1" in
    --app-dir) APP_DIR="$2"; shift 2 ;;
    --volume)  VOLUME="$2";  shift 2 ;;
    --hora)    HORA="$2";    shift 2 ;;
    --remover) REMOVER=1;    shift ;;
    *) echo "[cron] ✗ argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

ATUAL="$(crontab -l 2>/dev/null || true)"
SEM_A_NOSSA="$(printf '%s\n' "$ATUAL" | grep -vF "$MARCA" | grep -v 'run_restore_drill.sh' || true)"

if [ "$REMOVER" -eq 1 ]; then
  printf '%s\n' "$SEM_A_NOSSA" | crontab -
  echo "[cron] ✓ entrada do drill removida"
  crontab -l 2>/dev/null | grep -c . | sed 's/^/[cron] linhas restantes: /'
  exit 0
fi

[ -n "$APP_DIR" ] || { echo "[cron] ✗ --app-dir é obrigatório" >&2; exit 2; }
[ -d "$APP_DIR" ] || { echo "[cron] ✗ --app-dir não existe: $APP_DIR" >&2; exit 2; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$APP_DIR/drill/cron.log"

# `--metrics-dir` é um caminho do HOST, que o usuário do cron alcança. O drill
# grava ali (com o portão de higiene) e depois PUBLICA a cópia no volume
# `backups`, por container — é de lá que o smoke lê, de dentro do container de
# backup, porque o mountpoint do volume é root-only no host.
# UMA nova tentativa, 10 minutos depois, e o comando repetido na propria linha
# do crontab — de proposito.
#
# Medido em 13/09: a primeira execucao manual do drill falhou na fase 2
# ("postgres efemero nao ficou pronto") porque rodou no mesmo minuto de um
# `docker compose up --force-recreate`. Rodando sozinho em seguida, passou. Um
# tropeco desses as 03:00 nao deixaria metrica, e a tolerancia de 30h expiraria
# no meio da manha seguinte: o smoke ficaria vermelho por barulho, e alerta que
# dispara por barulho ensina a ignorar alerta (INTENT, Limites).
#
# A repeticao do comando na linha e feia e fica. A alternativa era um script
# gerado em disco, fora do versionamento, ou um retry DENTRO do drill — e retry
# dentro da coisa que se mede contamina "o drill passou". Assim quem roda
# `crontab -l` ve a politica inteira, sem procurar.
DRILL="bash scripts/run_restore_drill.sh --env-file ${APP_DIR}/.env.staging --volume ${VOLUME} --workdir ${APP_DIR}/drill --metrics-dir ${APP_DIR}/drill/metrics"
LINHA="0 ${HORA} * * * cd ${REPO} && { ${DRILL} || { sleep 600; ${DRILL}; }; } >> ${LOG} 2>&1"

mkdir -p "$APP_DIR/drill"
printf '%s\n%s\n%s\n' "$SEM_A_NOSSA" "$MARCA" "$LINHA" | grep -v '^$' | crontab -

echo "[cron] ✓ instalado para as ${HORA}:00 (backup roda 02:00 — o drill vem depois)"
echo "[cron] entrada:"
crontab -l 2>/dev/null | grep -A 1 -F "$MARCA" | sed 's/^/[cron]   /'
echo "[cron] log: $LOG"
