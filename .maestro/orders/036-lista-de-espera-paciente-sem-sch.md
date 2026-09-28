<!-- maestro-order v1
id: 036
ts: 2026-09-28T10:28:52-03:00
epoch: 1790602132
head: e92da9a57ffd3ad15fb85a716560983fedd922da
branch: order/036-lista-de-espera-paciente-sem-sch
intent_version: 6
intent_hash: f6a0c0bc
author_session: desconhecido
-->
# Ordem 036 — Lista de espera: paciente sem schedule.read deixa de receber 500


## Escopo
Defeito medido pelo gerente em 28/09: quem não tem `schedule.read` cai no ramo que faz
`Patient.objects.get(user=request.user)` (`apps/emr/views_waitlist.py:147` na listagem e `:188`
na criação). `Patient` não tem campo `user`, então a resposta é 500 — inclusive para o paciente
do portal, a quem o ramo se destina.

Conserto: o paciente é identificado pelo `PatientPortalAccess` ativo, o mesmo vínculo que o
portal já usa. Sem vínculo, a lista volta vazia e o POST sem `patient_id` responde 400.

## Prova exigida
- teste vermelho que reproduz o 500 na listagem e no POST antes do conserto;
- teste de que um paciente não vê a lista de espera de outro;
- recibo `order-36` com a suíte inteira na lab, como as ordens 029 a 035.

## Fora desta ordem
A limpeza (rota `imaging/viewer-auth/`, docstring da `ObservationReadView`, `except` da
`PatientReadView`) é a 037. O reenvio de convite é a 038: decidido pelo Diretor em 28/09 —
reemitir token novo sobre o mesmo registro, preservando a trilha.

## Contrato de execução
- Trabalhe APENAS no branch `order/036-lista-de-espera-paciente-sem-sch`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-36 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 036` (você não fecha a própria ordem).
