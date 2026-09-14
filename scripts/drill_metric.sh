#!/usr/bin/env bash
# Vitali — métrica do drill de restore (ordem 011)
# ─────────────────────────────────────────────────────────────────────────────
# Escreve `vitali_restore_drill_last_success_timestamp_seconds` — e SÓ escreve
# quando o drill realmente passou e a limpeza foi verificada.
#
# POR QUE O PORTÃO VIVE AQUI, e não no chamador. O `run_restore_drill.sh` mede
# as três coisas que definem "limpo" (containers remanescentes, `.dump` em claro
# em /tmp e no workdir) e o resultado da fase 1. Se ele também decidisse quando
# escrever, bastaria alguém chamar o escritor direto para furar o portão. Aqui o
# escritor EXIGE os números e recusa-se a assumir qualquer um deles.
#
# Contador ausente é ERRO, nunca zero. Tratar ausência como sucesso é a mesma
# forma do `grep -c` sobre saída vazia lido como "nenhum problema" — o defeito
# que esta série de ordens encontrou três vezes em lugares diferentes.
#
# A disciplina é a de `scripts/backup.sh` §"Success metric": escrita depois do
# trabalho inteiro, nunca antes. Métrica que mente é pior que métrica nenhuma,
# porque tira de quem lê a dúvida que o faria ir olhar.
#
# Uso:
#   bash scripts/drill_metric.sh --metrics-dir /backups/metrics \
#     --duration 372 --fase1 ok --containers 0 --claros-tmp 0 --claros-work 0
set -euo pipefail

METRICS_DIR=""
DURATION=""
FASE1=""
CONTAINERS=""
CLAROS_TMP=""
CLAROS_WORK=""

while [ $# -gt 0 ]; do
  case "$1" in
    --metrics-dir) METRICS_DIR="$2"; shift 2 ;;
    --duration)    DURATION="$2";    shift 2 ;;
    --fase1)       FASE1="$2";       shift 2 ;;
    --containers)  CONTAINERS="$2";  shift 2 ;;
    --claros-tmp)  CLAROS_TMP="$2";  shift 2 ;;
    --claros-work) CLAROS_WORK="$2"; shift 2 ;;
    *) echo "[metric] ✗ argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

for par in "metrics-dir:$METRICS_DIR" "duration:$DURATION" "fase1:$FASE1" \
           "containers:$CONTAINERS" "claros-tmp:$CLAROS_TMP" "claros-work:$CLAROS_WORK"; do
  nome="${par%%:*}"
  valor="${par#*:}"
  if [ -z "$valor" ]; then
    echo "[metric] ✗ --$nome é obrigatório. Ausência não é zero." >&2
    exit 2
  fi
done

if [ "$FASE1" != "ok" ]; then
  echo "[metric] ✗ fase 1 não passou ($FASE1) — métrica NÃO escrita" >&2
  exit 1
fi

if [ "$CONTAINERS" -ne 0 ] || [ "$CLAROS_TMP" -ne 0 ] || [ "$CLAROS_WORK" -ne 0 ]; then
  echo "[metric] ✗ limpeza não verificada (containers=$CONTAINERS" \
       "claros_tmp=$CLAROS_TMP claros_work=$CLAROS_WORK) — métrica NÃO escrita" >&2
  exit 1
fi

mkdir -p "$METRICS_DIR"
ALVO="$METRICS_DIR/vitali_restore_drill.prom"
TEMPORARIO="$ALVO.$$"

# Escrita atômica: o coletor textfile lê o diretório a qualquer momento, e um
# arquivo lido pela metade vira métrica malformada — que o Prometheus descarta
# em silêncio, deixando o painel verde por ausência de dado.
cat > "$TEMPORARIO" <<PROM
# HELP vitali_restore_drill_last_success_timestamp_seconds Unix timestamp do último drill de restore completo e limpo.
# TYPE vitali_restore_drill_last_success_timestamp_seconds gauge
vitali_restore_drill_last_success_timestamp_seconds $(date +%s)
# HELP vitali_restore_drill_duration_seconds Duração do último drill de restore bem-sucedido.
# TYPE vitali_restore_drill_duration_seconds gauge
vitali_restore_drill_duration_seconds $DURATION
PROM
mv "$TEMPORARIO" "$ALVO"
echo "[metric] ✓ $ALVO escrito (duração ${DURATION}s)"
