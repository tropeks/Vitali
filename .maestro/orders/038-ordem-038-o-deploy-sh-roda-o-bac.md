<!-- maestro-order v1
id: 038
ts: 2026-10-02T06:45:15-03:00
epoch: 1790934315
head: 91e0ade769d735bfff08cd3ede76429f5cfa95f3
branch: order/038-deploy-backfill
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 038 — o deploy.sh roda o backfill_audit_partitions sozinho quando o ensure_audit_partitions acusa linha na DEFAULT


> **Direção:** INTENT v6, Prioridade 2 (recuperação provada) e Limites ("sinal verde tem que
> significar verde"). Achado do ship de 28/09: o primeiro deploy da `core.0043` sobre um
> banco com trilha antiga para no `ensure_audit_partitions`, porque as linhas legadas vão
> para a DEFAULT. O remédio manual é `backfill_audit_partitions --execute` e um segundo
> `deploy.sh`. Produção vai bater no mesmo ponto.

## O que fazer
- `scripts/migrate_schemas.sh`: se o `ensure_audit_partitions` falhar, roda
  `backfill_audit_partitions --execute` (contêiner descartável da imagem nova) e repete o
  `ensure`. Segunda falha aborta o deploy antes do `up`. Sem falha, nenhum backfill.
- `docs/DEPLOY.md`: o passo 3 descreve o backfill automático, o que ele move e o aviso de
  que o backfill trava por grupo (ADR-0001), então em clínica grande o deploy demora.
- Provas: vermelho primeiro (`test_deploy_order.py`, `docker` falso); recibo `order-38`.

## Fora desta ordem
O mecanismo da 037 e o reenvio de convite (039).

## Contrato de execução
- Trabalhe APENAS no branch `order/038-deploy-backfill`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-38 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 038` (você não fecha a própria ordem).
