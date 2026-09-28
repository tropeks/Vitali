<!-- maestro-order v1
id: 033
ts: 2026-09-28T01:41:06-03:00
epoch: 1790570466
head: 7dd140c0f3769e2a2355c75c3bef8a1ef3f5f31b
branch: order/033-invite-token-hash
intent_version: 6
intent_hash: f6a0c0bc
author_session: 9c684afb-6ba9-405a-9c4b-a3f6313897c6
-->
# Ordem 033 — invite_token guardado só como hash

> **Direção:** INTENT v6, **Prioridade 4** (compliance como gate) e **§Limites**. Achado da
> 031, posto na fila pelo Diretor em 28/09, depois do aceite da 032: "Token em texto claro no
> banco entra na fila como ordem própria, com hash e migration".

## O que a medição mostrou

A 031 tirou o `invite_token` das respostas de leitura. No banco ele continua em claro
(`patient_portal_patientportalaccess.invite_token`, `unique`, indexado): quem lê a tabela,
um dump ou um backup tem o link de ativação de todo convite em aberto. Medido no tip
`7dd140c`, o token em claro é lido em quatro lugares:
- `AccessActivateView`: busca `objects.get(invite_token=token)`;
- `invite_delivery.build_activation_url`: monta `/portal/activate?token=…` para o WhatsApp
  e o e-mail;
- `PatientPortalInviteSerializer`: devolve no 201 (a saída manual decidida na 031);
- o Django admin: `search_fields` e `readonly_fields`.

O frontend só ENVIA o token (`portalApi.activateInvite`). Nenhuma outra tabela, seed ou
fixture o grava.

## O corte

- **Model:** `invite_token_hash` (SHA-256 hex, `unique`, indexado, não editável) no lugar de
  `invite_token`. O token tem 256 bits aleatórios (`secrets.token_urlsafe(32)`): um hash
  rápido basta, não há dicionário a atacar, e a busca continua por índice.
- **O token em claro existe só na instância que o cunha** (`save()` do objeto novo), como
  atributo que não vai ao banco. A entrega e o 201 usam essa instância; relida do banco, ela
  não tem token.
- `PatientPortalAccess.find_by_invite_token(token)` busca pelo hash; o activate usa. Colar o
  próprio hash não ativa nada.
- **Entrega:** `build_activation_url` recusa por nome instância sem token (seria um link
  `?token=None` mandado calado ao paciente); `deliver_portal_invite`, que nunca levanta, loga
  erro e não entrega.
- **Admin:** sai da busca e do read-only (não há mais o que mostrar). Na criação pelo admin,
  se a entrega falhar por todos os canais, o link sai UMA vez na mensagem da tela, como o
  201 na API. Era o admin que a 031 apontou como única saída depois do 201.
- **Migration `0004_invite_token_hash`:** adiciona o hash, grava o SHA-256 do token de cada
  linha, torna o hash obrigatório e único, e derruba a coluna em claro. **Os convites já
  enviados continuam valendo**: o link que o paciente tem casa com o hash gravado.
  **Reverter recusa, nomeando o motivo:** o claro não volta de um hash, e recriar a coluna
  com tokens novos mataria calado todo convite aberto.

## Provas

- **Vermelho primeiro, publicado sozinho** (`test_invite_token_hash.py`): a coluna em claro
  não existe; nenhuma coluna guarda o token; relida do banco a instância não tem token;
  salvar de novo não troca o hash; o activate com o token funciona e com o hash não; o 201
  devolve o token cujo hash está no banco; entrega de instância relida recusa; admin sem o
  token na busca e no read-only, e com o link na mensagem só quando a entrega falha; a
  função de dados da migration grava o hash de cada convite, o hash da migration é o do
  model, e reverter recusa.
- **A migration no caminho real** (`test_invite_token_hash_migration.py`): no schema do
  tenant de teste, a tabela volta fisicamente ao formato anterior à 0004 (coluna em claro,
  hash anulável), um convite é gravado pelo model histórico com token em claro, as
  operações da 0004 rodam para frente, e o convite ativa pela API com o token antigo. Sem a
  função de dados, o `AlterField` para `NOT NULL` quebraria: o teste não passa por acaso.
- Recibo `order-33` na lab, suíte inteira, no tip do branch.

## Fora desta ordem

- Reenvio de convite (token novo, entrega de novo): continua no backlog.

Nenhuma mudança de permissão. Uma migration, em app de tenant (roda por schema).


## Contrato de execução
- Trabalhe APENAS no branch `order/033-invite-token-hash`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-33 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 033` (você não fecha a própria ordem).
