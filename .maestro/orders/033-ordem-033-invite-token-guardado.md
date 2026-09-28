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

- **Model:** `invite_token_hash` (SHA-256 hex, `unique`, não editável) é o que convite novo
  grava; a coluna em claro fica NULL para ele. O token tem 256 bits aleatórios (`secrets.token_urlsafe(32)`): um hash
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
- **Migration `0004_invite_token_hash` — fase 1 de 2** (a regra de
  `docs/TENANT_MIGRATIONS.md`: nenhuma migration de tenant derruba coluna junto com a criação
  da nova, porque `migrate_schemas` roda tenant a tenant e a release anterior tem de rodar
  contra o schema novo). Ela só expande: adiciona o hash (anulável, único), tira o NOT NULL
  da coluna em claro (convite novo grava NULL nela; no Django ela vira
  `invite_token_legado`, a mesma coluna) e grava o SHA-256 de cada convite existente. **Os
  convites já enviados continuam valendo.** Reverter é seguro e não toca em dado.
- **O que ainda fica em claro, e até quando:** só o token dos convites criados ANTES do
  deploy da 033. Ativar ou revogar apaga o claro daquele convite; os demais expiram em 7
  dias (`invite_expires_at`), e a partir daí o claro não ativa nada (o activate recusa
  convite expirado).
- **Fallback da fase 1:** uma linha gravada pela release anterior (claro, hash NULL) ainda
  ativa pelo token, casada por valor SÓ quando o hash é NULL, e ganha o hash na hora.
- **Ordem 034 (fase 2), depois do deploy desta:** hash obrigatório, a coluna em claro sai, o
  fallback sai. Condição: a 0004 aplicada em todos os tenants e 7 dias passados.

## Revisão (revisor, antes do PR)

- **P1, corrigido:** a primeira versão da 0004 criava o hash E derrubava a coluna em claro
  numa migration só, irreversível. Isso viola `docs/TENANT_MIGRATIONS.md`, e com o deploy
  real (`up -d` antes de `migrate_schemas`, `docs/DEPLOY.md`) o portal inteiro de um tenant
  ainda não migrado cairia, porque `IsPortalSelfAccess` consulta o model em todo request de
  `/portal/me/*`. Refeita como fase 1 (acima). Essa versão nunca saiu do branch; a lab
  reaproveita o banco de teste (`--reuse-db`) e foi recriada com `--create-db`.
- **Achado de fora, para o Diretor:** `docs/DEPLOY.md` sobe o código novo (`up -d`) ANTES de
  `migrate_schemas`. Com isso, TODO `AddField` de tenant tem uma janela em que o código novo
  consulta uma coluna que ainda não existe, e isso contradiz a premissa de
  `TENANT_MIGRATIONS.md`. Não é desta ordem: fica registrado.
- P3: `unique` + `db_index` redundantes: o campo novo usa só `unique`.

## Provas

- **Vermelho primeiro, publicado sozinho** (`test_invite_token_hash.py`): a coluna em claro
  não existe; nenhuma coluna guarda o token; relida do banco a instância não tem token;
  salvar de novo não troca o hash; o activate com o token funciona e com o hash não; o 201
  devolve o token cujo hash está no banco; entrega de instância relida recusa; admin sem o
  token na busca e no read-only, e com o link na mensagem só quando a entrega falha; a
  função de dados da migration grava o hash de cada convite e o hash da migration é o do
  model.
- **A migration no caminho real** (`test_invite_token_hash_migration.py`, no schema do
  tenant de teste, dentro da transação): convite gravado pelo model da release anterior
  antes da 0004 ativa depois dela; a release anterior grava no schema novo e a nova ativa;
  desfazer a 0004 com um convite desta fase não exige tocar em dado.
- Convite da release anterior (claro, hash NULL) ativa pelo token, ganha o hash e perde o
  claro; revogar apaga o claro; colar o hash não casa com o claro.
- Recibo `order-33` na lab, suíte inteira, no tip do branch.

## Fora desta ordem

- Reenvio de convite (token novo, entrega de novo): continua no backlog.

Nenhuma mudança de permissão. Uma migration aditiva, em app de tenant (roda por schema).


## Contrato de execução
- Trabalhe APENAS no branch `order/033-invite-token-hash`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-33 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v6 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 033` (você não fecha a própria ordem).
