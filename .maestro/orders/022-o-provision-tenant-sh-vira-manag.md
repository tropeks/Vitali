<!-- maestro-order v1
id: 022
ts: 2026-09-25T09:32:07-03:00
epoch: 1790339527
head: 1670a07f9a881cae5429be92f40829aea0523421
branch: order/022-provision-tenant-command
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 022 — O provision_tenant.sh vira management command: um caminho so para criar clinica, sem shell dentro do Python

> **Direção:** INTENT v5, **§Prioridade 1**: "Isolamento entre tenants antes de qualquer
> feature. [...] Mudança em auth, tenant, permissão ou migration passa por especialista e
> teste". Criar clínica é o ato fundador do tenant, e hoje ele tem quatro portas.
>
> **Execução headless, prova pelo CI.** A forge **não roda** compose do Vitali (regra do
> Imediato, 17/09): nem para testar, nem "só um minuto". Esta ordem não sobe stack em lugar
> nenhum, não toca staging nem produção e não provisiona clínica real. Tudo se prova em
> pytest no job `Backend — Tests` do CI, que roda em push para `order/**`.

## A premissa do brief estava errada, e o buraco real é outro

O brief de 18/09 dizia que `scripts/provision_tenant.sh` era "o **único** caminho que cria
clínica" e que "todo tenant nasce incompleto". Conferido no código em 25/09, **as duas
coisas são falsas**. Existem quatro caminhos:

| caminho | onde | admin, papéis, membership, assinatura e flags | forma |
|---|---|---|---|
| `services.provisioning.provision_tenant` | `apps/core/services/provisioning.py`, chamado por `POST /api/v1/public/signup/` (S-132) | **sim**, e com rollback que derruba o schema se falhar no meio | serviço testado |
| `TenantRegistrationView` | `apps/core/views.py:555`, `POST /api/v1/platform/tenants` | papéis, admin e membership **duplicados à mão** (não chama o serviço) | view |
| `scripts/provision_tenant.sh` | shell + `manage.py shell -c` | **não**: só `Tenant` + `Domain` + `migrate_schemas` | **interpola `$SCHEMA_NAME`, `$DOMAIN_NAME` e `$TENANT_NAME` dentro de código Python** |
| `make create-tenant` | `Makefile:107` | **não**: só `Tenant` + `Domain` | `input()` interativo dentro de `shell -c` |

(`bootstrap_beta` também cria tenant, mas é para ambiente novo inteiro: cria o `public` e
uma clínica. Fica fora do escopo e não pode quebrar; `test_bootstrap_beta.py` o guarda.)

O que as duas portas legadas entregam além de `Tenant` + `Domain` vem **só** do signal
`create_tenant_defaults_on_new_tenant` (`apps/core/signals.py:675`): `TenantAIConfig`
desligado e a flag `emr`. Não criam papel, admin, membership nem assinatura. Alguém
termina a clínica na mão, e esse trabalho não deixa registro em lugar nenhum.

A interpolação é o defeito grave. O nome da clínica entra entre aspas simples **no fonte
Python** que o `shell -c` executa. Um nome com apóstrofo (`Clínica D'Ávila`) quebra o
script. Um nome escolhido para isso executa código arbitrário **dentro do contêiner
Django, com as credenciais do banco de todas as clínicas**.

### O achado que não estava na fila: tenant criado por anônimo

`TenantRegistrationView` tem **`permission_classes = [permissions.AllowAny]`** e **nenhum
throttle**. O comentário da rota em `urls_public.py` diz "engineer/platform-admin flow", e
o `apps/core/tests/test_auth.py:299` (`TenantRegistrationTestCase`) afirma que um
`APIClient` **sem autenticação** recebe `201`. Ou seja: qualquer pessoa que alcance o
domínio público cria um tenant com schema próprio, `migrate_schemas` inteiro e um admin
**com a senha que escolheu**. Cada chamada custa um schema e todas as migrations. O signup
self-serve, que é público de propósito, tem throttle justamente por isso, e o admin dele
nasce sem senha: ativa pelo link do e-mail.

Isto foi **lido no código, não medido em staging**. Esta ordem não sonda staging. Se a rota
responde por lá, é a primeira coisa que o relatório da ordem deve dizer ao Imediato.

### O buraco que nenhum dos quatro caminhos fecha: a partição de auditoria

A ordem 021 pôs `ensure_audit_partitions` no deploy (depois do `migrate_schemas`) e no
Celery Beat **diário**. **Nenhum caminho de criação de tenant a chama.** Uma clínica criada
às 10h escreve `AuditLog` (login do admin, primeira leitura de paciente) até a próxima
rodada do Beat, e essas linhas caem na **folha DEFAULT do mês**.

A 021 mediu o que acontece depois: com linha na DEFAULT, criar a folha dedicada falha com
`IntegrityError: updated partition constraint for default partition ... would be violated
by some row`. E `ensure_audit_partitions.handle()` percorre os tenants num laço **sem
isolar falha por tenant**. Então a rodada seguinte do Beat pode morrer na clínica nova e
deixar sem partição do mês seguinte **todas as clínicas que vêm depois dela no laço**.

Isto é **hipótese derivada da leitura do código e da medição da 021, ainda não
reproduzida**. O passo 1 abaixo a prova ou a derruba.

## O trabalho

**0. Teste vermelho antes de tudo** (commit `test(...)` que **falha** no tip atual, como nas
ordens 008 a 011):
   * `POST /api/v1/platform/tenants` anônimo **não** pode criar tenant;
   * uma escrita real de `AuditLog` pelo ORM, feita logo depois de provisionar uma clínica,
     cai em **folha dedicada**. A asserção é sobre `tableoid::regclass`, sem SQL preparado
     pela fixture: a lição da 021 é que teste que constrói à mão a condição medida mede a
     si mesmo;
   * `ensure_audit_partitions` com uma clínica cuja DEFAULT do mês tem linha **não aborta**
     as demais.

   Se algum desses três **não** ficar vermelho no tip atual, registre o resultado no relatório
   e tire o item correspondente do escopo. Não invente defeito para caber na ordem.

**1. Um caminho só: o serviço.** `services.provisioning.provision_tenant` é a fonte única.
   * `TenantRegistrationView` passa a exigir as permissões de plataforma que as vizinhas já
     usam (`_PLATFORM_PERMS`, em `views_platform.py`) e **delega ao serviço** em vez de
     duplicar papéis/admin/membership. O contrato de resposta (`tenant`, `domain`,
     `admin_user`, `trial_ends_at`) se mantém para quem autentica.
   * O teste que afirmava `201` anônimo **inverte**: anônimo → `401`/`403`, nada criado.

**2. `manage.py provision_tenant`**, casca fina sobre o serviço, sem lógica própria de
   criação:
   * argumentos explícitos: `--slug`, `--name`, `--domain` (explícito; não deriva de
     `Host`), `--owner-email`, `--owner-name`, `--cnpj` opcional e `--modules`, validado
     contra `ALLOWED_MODULE_KEYS`. Módulo desconhecido sai com erro nomeando o módulo;
   * **nenhum segredo atravessa a linha de comando**: o comando **não tem** argumento de
     senha. O admin nasce sem senha utilizável e ativa pelo convite que o serviço já emite
     (`issue_password_set_invitation`). O token **não** vai para stdout nem para log. Um
     teste afirma que o parser não aceita `--password` nem variação;
   * **idempotente**: rodar de novo com os mesmos argumentos sai `0`, relata "já existe"
     item a item e não cria nada. Rodar com argumento conflitante (mesmo slug, outro dono ou
     outro domínio) sai `≠0` nomeando o conflito. **Nunca** derruba tenant que já existia.
     O rollback do serviço (`_drop_tenant`) só pode alcançar o tenant que a própria
     chamada criou, e um teste prova isso com uma clínica pré-existente e cheia de dado;
   * **o valor entra como dado, nunca como fonte**: nome com `'`, `"`, `;`, quebra de linha
     e `__import__('os')` é gravado literalmente, e um teste afirma isso.

**3. A partição nasce com a clínica.** Dentro do serviço, e portanto também no signup:
   depois do schema, garantir a folha dedicada do mês corrente e do seguinte para o
   tenant novo (`partitioning.ensure_tenant_partition`, que já existe). Se o passo 0
   confirmar o laço frágil, `ensure_audit_partitions` passa a isolar falha **por tenant**:
   continua os outros, nomeia quem falhou, sai `≠0` no fim e aponta
   `backfill_audit_partitions`.

**4. Retenção nasce no padrão de fábrica.** Clínica nova **não** ganha `TenantAuditRetention`
   com `purge_enabled=True` por nenhum caminho. A ausência de linha continua valendo
   240 meses com expurgo desligado (ordem 021, ADR-0001). Um teste afirma isso para clínica
   recém-provisionada.

**5. As portas legadas fecham.** `scripts/provision_tenant.sh` sai do repositório. `make
   create-tenant` passa a chamar `manage.py provision_tenant` com argumentos (sem `input()`
   dentro de `shell -c`). Atualize `README.md`, `docs/DEVELOPMENT.md` e o docstring de
   `views_signup.py`, que ainda cita o `.sh`.

## Prova exigida

Tudo em pytest, rodando **no CI**. Nenhuma prova depende de stack de pé.

* os três vermelhos do passo 0 ficam verdes, e o histórico do branch mostra o commit
  vermelho **antes** do conserto;
* provisionar pelo comando entrega a mesma clínica que o signup entrega: tenant, domínio,
  papéis padrão, admin, membership, assinatura, flags dos módulos e folhas de auditoria.
  Asserção campo a campo, comparando os dois caminhos;
* **isolamento**: provisionar a clínica B não altera linha, papel, membership nem partição
  da clínica A;
* idempotência, conflito nomeado, rollback que não alcança tenant pré-existente, valor
  hostil gravado literal e nenhum argumento de senha: cada um com teste próprio;
* `test_bootstrap_beta.py` e `test_self_serve_signup.py` continuam verdes, sem editar
  asserção.

**Recibo:** com o PR aberto contra `onda0-perimetro-multitenant` e o CI verde no tip do
branch, grave
`maestro evidence --record --label order-22 -- gh run watch <run-id> --exit-status`, com o
`<run-id>` do workflow `CI` naquele tip. **Recibo antes do PR ser mesclado**: a ordem 016
ficou aberta justamente por isso.

## Ask-First

* Qualquer mudança em `DEFAULT_ROLES`, em `_PLATFORM_PERMS` ou no contrato de
  `POST /api/v1/public/signup/`: pare e pergunte.
* Se fechar `platform/tenants` quebrar algum consumidor real (frontend, E2E ou runbook),
  pare e reporte **antes** de adaptar o consumidor. Conferido em 25/09: nem `frontend/`
  nem o job E2E chamam `POST platform/tenants`. O E2E cria o tenant de teste por
  `manage.py shell -c` embutido no `ci.yml` (uma quinta porta, sem interpolação de
  variável). Migrá-lo para o comando novo é bem-vindo, mas não é exigido.

## Fora desta ordem

* Rodar qualquer coisa na forge com compose; subir stack na lab; provisionar clínica em
  staging ou produção.
* `bootstrap_beta`: não muda, só não pode quebrar.
* Offboarding (derrubar tenant, exportar a trilha dele): ordem própria, e depende do
  backend frio S3/Glacier da 020.
* Sorologia de doador fora do grafo de `Patient`: próxima da fila, ordem própria.

## Contrato de execução
- Trabalhe APENAS no branch `order/022-provision-tenant-command`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-22 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 022` (você não fecha a própria ordem).
