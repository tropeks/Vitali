<!-- maestro-order v1
id: 039
ts: 2026-10-02T07:39:39-03:00
epoch: 1790937579
head: 91e0ade769d735bfff08cd3ede76429f5cfa95f3
branch: order/039-reenvio-convite
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 039 — reenvio de convite do portal: token novo sobre o mesmo registro, preservando a trilha


> **Direção:** INTENT v6, Prioridade 1 (isolamento) e Prioridade 4 (a trilha não se perde).
> Decisão do Diretor em 28/09: reemitir token novo sobre o mesmo registro, preservando a
> trilha. Convite expirado hoje não tem saída: a clínica cria outro acesso ou mexe no banco.

## O que fazer
- `POST /api/v1/portal/access/<id>/resend/` (`users.write` + módulo do portal): só para
  acesso `invited`, vencido ou não. Cunha token novo, grava o hash novo (o velho deixa de
  valer), zera a coluna em claro legada, renova a validade (7 dias) e entrega pelo mesmo
  caminho do convite (`deliver_portal_invite`, fail-open). Devolve o token novo, como o 201.
- Mesmo registro: `id`, `invited_at` e `created_by` ficam. `AuditLog` `portal_invite_resent`
  com quem reenviou e a nova validade.
- `active` e `revoked` recusam com 409: reenviar não reabre acesso revogado.
- Só usa o hash: compatível com a fase 2 (ordem 034, que derruba a coluna em claro).
- Provas: vermelho primeiro; recibo `order-39`.

## Fora desta ordem
UI do botão "reenviar" (a API primeiro); limite de frequência do reenvio.

## Contrato de execução
- Trabalhe APENAS no branch `order/039-reenvio-convite`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-39 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 039` (você não fecha a própria ordem).
