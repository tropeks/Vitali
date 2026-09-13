#!/usr/bin/env bash
# Reporter da Ponte — hook de `Stop` (passo 5 do plano do herdr).
#
# Lê a ÚLTIMA linha do turno e, se ela for a linha de protocolo
# `[spock] aguardando: <o quê>`, reporta três tokens na PRÓPRIA pane por
# `herdr pane report-metadata`. Nada mais. Contrato:
# `ponte-daemon/docs-ops/003/CONTRATO-TOKENS.md` (aprovado pelo Diretor em
# 2026-09-12); instalação autorizada por ele para ESTE projeto apenas.
#
# ============================ A REGRA QUE MANDA ============================
# ESTE SCRIPT SAI 0 SEMPRE. Um hook de `Stop` que sai != 0 pode impedir a
# sessão de encerrar o turno e prender o agente num laço. Nenhum erro daqui
# — stdin vazio, JSON malformado, herdr ausente, socket fora, pane sem id,
# timeout — pode virar exit != 0. Por isso: sem `set -e`, toda chamada
# externa com `timeout`, e um `exit 0` explícito no fim.
# ===========================================================================
#
# Rollback: `git revert` do commit que trouxe este arquivo e o
# `.claude/settings.json`. O daemon não muda em nada — ele só passa a não
# receber os tokens, como era antes.

set -u
trap 'exit 0' ERR   # rede final: qualquer coisa não prevista sai 0 mesmo assim

PANE="${HERDR_PANE_ID:-}"
[[ -n "$PANE" ]] || exit 0                      # fora de pane do herdr: nada a fazer
command -v herdr >/dev/null 2>&1 || exit 0      # sem herdr: silêncio
command -v python3 >/dev/null 2>&1 || exit 0

payload=$(cat 2>/dev/null || true)
[[ -n "$payload" ]] || exit 0

# `last_assistant_message` do payload do Stop — NUNCA `transcript_path` + parse:
# o C-11 mediu corrida em 2 de 3 turnos naquela via. O C-11 também provou que a
# linha chega íntegra aqui, com acento e sem truncamento.
#
# A sanitização segue o contrato: charset `^[A-Za-z0-9 .,:/_+-]{1,80}$` (C-1,
# revisado pelo Diretor para tirar `;` `(` `)` — se a linha cair num shell, `;`
# encadeia comando e parênteses são subshell). O que não casa é REMOVIDO, não
# rejeita a linha: o texto é humano e vai ter acento; o token é ASCII.
#
# Corte em 79 + `+` (§2.3/C-12) — nunca deixar o herdr truncar, porque ele corta
# em 80 EM SILÊNCIO.
waiting=$(printf '%s' "$payload" | timeout 5 python3 -c '
import json, re, sys, unicodedata
try:
    msg = json.load(sys.stdin).get("last_assistant_message") or ""
except Exception:
    sys.exit(0)
achado = ""
for linha in msg.splitlines():
    l = linha.strip()
    if l.startswith("[spock] aguardando:"):
        achado = l.split(":", 1)[1].strip()
if not achado:
    sys.exit(0)
# acento vira a letra base (ção -> cao) antes de filtrar, para o texto
# sobreviver em vez de virar buraco
achado = unicodedata.normalize("NFKD", achado).encode("ascii", "ignore").decode()
achado = re.sub(r"[^A-Za-z0-9 .,:/_+-]", "", achado)
achado = re.sub(r"\s+", " ", achado).strip()
if not achado:
    sys.exit(0)
if len(achado) > 80:
    achado = achado[:79] + "+"
print(achado)
' 2>/dev/null || true)

[[ -n "$waiting" ]] || exit 0                   # sem linha de protocolo: não escreve nada

# epoch-ms, e o MESMO valor no --seq. Contador local não serve: o herdr conta
# `--seq` por --source e ignora EM SILÊNCIO (exit 0) qualquer valor <= ao último
# aceito — um contador reiniciaria em 0 no primeiro restart e todas as escritas
# seguintes sumiriam sem erro nenhum (C-13, medido).
seq=$(date +%s%3N 2>/dev/null || true)
[[ "$seq" =~ ^[0-9]{13}$ ]] || exit 0

# Só --token. NÃO passar --state-label/--title/--display-agent: tocar um deles
# substitui o grupo inteiro daquele --source (medido em HERDR-SEMANTICA.md).
# NÃO usar --applies-to-source (C-14: não isola, personifica).
# TTL de 12 h (C-9): cobre uma noite.
timeout 5 herdr pane report-metadata "$PANE" \
  --source ponte:manager \
  --token "ponte_waiting=$waiting" \
  --token "ponte_reason=handoff" \
  --token "ponte_seq=$seq" \
  --seq "$seq" \
  --ttl-ms 43200000 >/dev/null 2>&1 || true

# O exit code do herdr NÃO é confiável (C-13: --seq rejeitado sai 0), e de
# qualquer forma ele nunca poderia decidir o exit deste hook.
exit 0
