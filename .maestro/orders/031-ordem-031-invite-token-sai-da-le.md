<!-- maestro-order v1
id: 031
ts: 2026-09-27T20:24:28-03:00
epoch: 1790551468
head: 6145f472da51a373300ccf806bdfa8271459cf5e
branch: order/031-invite-token-fora-da-leitura
intent_version: 6
intent_hash: f6a0c0bc
author_session: 9c684afb-6ba9-405a-9c4b-a3f6313897c6
-->
# Ordem 031 — invite_token sai da leitura do acesso ao portal

> **Direção:** INTENT v6, **Prioridade 4** (compliance como gate) e **§Limites** ("Sinal
> verde tem que significar verde"). Achado do levantamento da 030; pedida pelo Diretor em
> 27/09, depois do aceite da 030, na frente da exportação fria (032).

## O que foi pedido, e o que a medição mostrou

`PatientPortalAccessSerializer` (`apps/patient_portal/serializers.py`) lista `invite_token`
entre os campos. É o segredo do link de ativação que `deliver_portal_invite` manda ao
paciente por WhatsApp ou e-mail (`/portal/activate?token=…`). O mesmo serializer responde:

| rota | quem chama | o token serve para |
|---|---|---|
| `GET /portal/access/` (até 200 linhas) | staff com `users.read` | nada |
| `GET /portal/access/{id}/` | staff com `users.read` | nada |
| `POST /portal/access/{id}/revoke/` | staff com `users.write` | nada (convite revogado) |
| `POST /portal/access/activate/` | o próprio paciente | nada (já o tinha, e acabou de gastá-lo) |
| `POST /portal/access/` (201) | staff com `users.write`, ao convidar | entregar à mão, se o WhatsApp e o e-mail falharem |

Medido no tip `6145f47`:
- **Nenhum consumidor de leitura.** No `frontend/`, `invite_token` só aparece em
  `portalApi.activateInvite`, que o ENVIA no corpo do POST; a tela de ativação só lê
  `status` da resposta. Não há tela de staff para `/portal/access/`.
- **O dano é limitado, e fica escrito como é:** `AccessActivateView` exige
  `access.user == request.user`, então o token sozinho não ativa a conta de outra pessoa. É
  segredo de credencial em listagem de leitura: vai para cache, log de proxy, devtools e
  HAR de quem só precisava ver o status dos convites. `users.read` não é `users.write`.
- `PatientPortalAccess` não está em `AUDITED_MODELS` (`apps/core/signals.py`): o token não
  vai para `new_data` de nenhuma linha de trilha. O Django admin mostra o campo como
  read-only para superusuário; fica.

## O corte

- `PatientPortalAccessSerializer` perde `invite_token`: GET da lista, GET do detalhe, revoke
  e activate deixam de devolvê-lo.
- `PatientPortalInviteSerializer`, subclasse, devolve o token **só no 201 do convite**: é o
  momento em que ele é criado, por quem tem `users.write`, e é a única saída manual quando
  `deliver_portal_invite` não entrega por nenhum canal (fail-open). É o padrão de chave de
  API: mostrada uma vez, na criação.
- `docs/API_SPEC.md` e `docs/SECURITY.md` dizem isso.

## Provas

- **Vermelho primeiro, publicado sozinho:** pelo caminho real (APIClient → roteador →
  view), GET da lista, GET do detalhe, revoke e activate não trazem a chave
  `invite_token`; o 201 do convite traz, e com o valor gravado.
- Recibo `order-31` na lab, suíte inteira, no tip do branch.

## Fora desta ordem

- O token fica em texto claro no banco (`unique`, indexado). Guardar só o hash exige
  migration e muda a busca do activate: registrado no backlog.
- Não há reenvio de convite, e `user` e `patient` são `OneToOne`: revogar não libera o par
  para um convite novo. Com o token fora da leitura, se a entrega falhar e o 201 se perder,
  hoje só o Django admin mostra o token. Reenvio de convite (token novo, entrega de novo)
  fica registrado no backlog.

Nenhuma migration, nenhuma mudança de model, nenhuma mudança de permissão.

## Contrato de execução
- Trabalhe APENAS no branch `order/031-invite-token-fora-da-leitura`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-31 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 031` (você não fecha a própria ordem).
accepted_at: 2026-09-27T22:35:07-03:00
accepted_session: desconhecido
accepted_tree: c8d275c99c62c05ef9d9b085017957e79530a68d
accepted_intent: 6
