# ADR-0001 — Retenção da trilha de auditoria: 20 anos, por tenant

* **Status:** Aceito
* **Data:** 2026-09-22
* **Quem decidiu:** Capitão, via Ponte (`01M325GP8W497HQWJ3GY55JPP9`, escolha `vinte_anos`)
* **Ordem que executa:** `.maestro/orders/021-retencao-da-trilha-de-auditoria.md` (continuação da
  ordem 020, que entregou o mecanismo de partição/expurgo sem o número do prazo)

## Contexto

A ordem 020 particionou `core_auditlog` por mês (`created_at`) e sub-particionou por tenant
(`schema_name`), e deu ao expurgo uma trava de exportação fria verificada
(`drop_partition(..., cold_export_receipt=...)`). O que faltava era **quanto tempo** guardar a
trilha antes de ela ser candidata a expurgo, e **quem** decide isso — e a resposta não podia vir
de uma constante no código: é uma decisão de negócio com base legal, e varia por tenant.

## Decisão

**Prazo de guarda da trilha de auditoria = 20 anos (240 meses), igual ao prontuário eletrônico.**
Configurável por tenant via `apps.core.models.TenantAuditRetention`
(`retention_months`, default 240), com o expurgo **desligado de fábrica**
(`purge_enabled`, default `False`). Um tenant sem linha configurada usa esses defaults — nunca
apaga por omissão.

### Base legal

* **Res. CFM 1.821/2007, art. 8** — prazo mínimo de 20 anos para guarda dos prontuários médicos.
* **Lei 13.787/2018, art. 6** — 20 anos a contar do último registro, para prontuário eletrônico.

A trilha de auditoria (`core_auditlog`) documenta o histórico de acesso e alteração do prontuário
eletrônico; o piso legal do prontuário foi adotado como piso da trilha que o instrumenta, por
decisão do Capitão — não há uma norma que fale da trilha de auditoria isoladamente.

### Unidade: meses, não dias

O que o mecanismo de expurgo derruba é uma **partição mensal** (`DROP TABLE`, nunca `DELETE`).
Contar o prazo em dias (como a ordem 020 fez, com `AUDIT_LOG_RETENTION_DAYS`) introduz uma borda:
20 anos são 7.305 ou 7.306 dias dependendo de quantos 29/fevereiro caem dentro da janela — uma
diferença de um dia que vira um bug de calendário impossível de reproduzir de forma determinística.
Contando em meses (240, exato), a unidade da configuração passa a ser a mesma unidade do
mecanismo que a usa. Esta migração de unidade foi feita nesta ordem, e não antes, porque o
expurgo nunca rodou em ambiente nenhum até aqui — não havia dado em produção para reinterpretar.

### Por tenant, não global

`AUDIT_LOG_RETENTION_DAYS`/`AUDIT_LOG_PURGE_ENABLED` (settings Django, ordem 020) foram
aposentados. `apps.core.management.commands.purge_audit_logs` resolve prazo e permissão
tenant a tenant, a partir de `TenantAuditRetention` — o mesmo padrão de
`apps.core.models.TenantAIConfig` (OneToOne com `core.Tenant`, PUBLIC schema/SHARED_APPS).
Isso é o que faz "ligado por cliente" ser uma frase literal: ligar o expurgo para o tenant A não
afeta o tenant B, mesmo quando os dois têm linhas no mesmo mês (a Prioridade 1 da direção —
isolamento entre tenants é o produto).

## Alternativa descartada

**Manter um único prazo/switch global** (o desenho da ordem 020, com `AUDIT_LOG_RETENTION_DAYS`
em dias). Descartada porque: (1) diferentes clínicas podem ter obrigações contratuais ou de
compliance distintas além do piso legal, e um único número global não comporta isso; (2) um
switch global de expurgo é uma arma de dois gumes — ligá-lo para testar em um tenant de baixo
risco liga-o para todos; (3) a unidade em dias, mantida, teria carregado a borda de bissexto para
sempre, e essa é a última janela barata para corrigi-la (o expurgo nunca rodou).

## Estimativa de armazenamento

**~3,6 GB/ano/tenant**, medida na ordem 020: ~10 mil linhas/dia/tenant (assumindo que as telas de
polling também gerem trilha de leitura, o pior caso já contemplado) × ~1 KB/linha ≈ 10 MB/dia ≈
3,6 GB/ano por tenant. Como `apps.core` está em `SHARED_APPS` e `core_auditlog` é uma
única tabela física no schema `public` (particionada, não uma tabela por tenant), esse custo
**soma entre todas as clínicas** — não é isolado por schema como as tabelas de `TENANT_APPS`. Em
20 anos de retenção, um tenant sozinho projeta ~72 GB só de trilha; a conta cresce linearmente
com o número de tenants ativos e é o principal argumento para, no futuro, mover partições antigas
para um backend frio (S3/Glacier — fora desta ordem) em vez de mantê-las quentes indefinidamente
mesmo com `purge_enabled=False`. (72 GB = 3,6 GB/ano × 20 anos, por tenant; não soma o custo de
índice, que a medição da ordem 020 tratou à parte.)

## Emenda do Imediato (22/09) — "não carimbo 20 anos em cima de expurgo inerte"

Medido em banco limpo, com a migration da 020 já aplicada e nenhuma linha escrita ainda:

```
AuditLog.objects.create(...)   -> cai em core_auditlog_default_default
ensure_tenant_partition        -> NÃO é chamada em nenhum lugar do código de produção
                                  (só num comentário e nos testes; sem rotina agendada)
```

**A lição, para não se repetir:** a ordem 020 entregou o mecanismo — `ensure_month_partition`,
`ensure_tenant_partition`, o expurgo por partição dedicada — mas **ninguém o chamava no caminho
real**. Os testes da 020 passavam porque cada um criava a partição à mão antes de escrever
(`partitioning.ensure_tenant_partition(...)` explícito na fixture, nunca invocado pelo código de
produção). Um teste que constrói à mão a condição que o sistema nunca produz **mede a si mesmo**,
não o sistema. **Aceite de mecanismo exige prova no caminho real — a escrita pelo ORM, sem ajuda
da fixture, tem de terminar na partição certa — não só a fixture provando que a função em si
funciona.** Esta ordem corrige isso: `RealOrmWriteLandsInDedicatedLeafTests` (test_auditlog_
partitioning.py) escreve via `AuditLog.objects.create(...)` sem `schema_name=` explícito — o
mesmo caminho de qualquer código de produção — e confere `tableoid::regclass` contra a partição
esperada.

### Duas armadilhas medidas, e como o código as resolve

1. **A DEFAULT trava a criação da partição correta.** Com uma linha em
   `core_auditlog_default_default` cujo `created_at` cai no mês M, `ensure_month_partition(M)`
   falha: `IntegrityError: updated partition constraint for default partition
   "core_auditlog_default" would be violated by some row`. O mesmo vale um nível abaixo: uma
   linha na DEFAULT de um mês já existente bloqueia `ensure_tenant_partition` para aquele tenant
   naquele mês. **Ordem de operação obrigatória:** tirar a linha da DEFAULT que a segura, DEPOIS
   criar a partição que deveria tê-la recebido — nunca o contrário (`apps.core.
   audit_partition_backfill.backfill_month`/`backfill_tenant_leaf`, cada um confirmado por teste
   contra Postgres real, não mockado).
2. **O trigger append-only recusa `DELETE`.** Tirar uma linha da DEFAULT é, fisicamente, um
   `DELETE` (mesmo que seguido de um `INSERT` que a recoloca no lugar certo), e a migration 0019
   bloqueia qualquer `DELETE` em `core_auditlog`: `AuditLog is append-only (CFM 1.821/2007): %
   blocked`. A saída é desabilitar o trigger **no `ALTER TABLE` do pai** (`core_auditlog`, não na
   partição individual onde o `DELETE` fisicamente acontece) pelo tempo mínimo — um grupo por vez
   (um mês, ou um mês+tenant), nunca a tabela inteira de uma vez — e reabilitá-lo logo em seguida,
   dentro da mesma transação do grupo.

### Plano de lock — hoje são poucas linhas; isto é para quando não forem

`ALTER TABLE core_auditlog DISABLE/ENABLE TRIGGER` toma lock que serializa contra qualquer escrita
concorrente na tabela particionada inteira (não só na partição fonte) pela duração do `DISABLE` +
`DELETE` + `ENABLE`. Para uma clínica em operação, com `core_auditlog` recebendo escrita o tempo
todo, isso não pode ser uma única transação cobrindo todo o histórico:

* **Um grupo por transação** (`apps.core.audit_partition_backfill.backfill_all` já faz isto: uma
  transação por mês na fase 1, uma transação por par mês+tenant na fase 2) — nunca uma transação
  para "tudo".
* **`SET LOCAL lock_timeout`** (5s, já no código) em cada transação — se o lock não vier
  rápido (porque há escrita concorrente pesada naquele instante), a transação falha e pode ser
  reprocessada depois, em vez de empilhar uma fila de espera indefinida atrás do `DISABLE
  TRIGGER`.
* **Rodar fora do horário de pico** da clínica (madrugada local) quando o volume por grupo for
  grande — o comando (`backfill_audit_partitions`) é idempotente e seguro para reexecutar; parar
  e retomar não perde nem duplica trabalho (o `--dry-run`, padrão, deixa medir o tamanho de cada
  grupo antes de decidir a janela).
* **Medir antes de rodar:** `backfill_audit_partitions` (sem `--execute`) relata a contagem de
  linhas de CADA grupo pendente sem tocar em nada — isso é o que dimensiona se um grupo cabe numa
  janela de manutenção ou precisa ser fatiado por `schema_name`/mês menor (a granularidade da
  ordem já é essa; não há um grupo "todos os meses de uma vez").
* **Nunca em produção ou staging por esta ordem** — só medido e provado em banco descartável na
  lab (ver relatório de execução). Rodar de verdade em staging/produção é decisão operacional
  posterior, com uma janela de manutenção reservada.

### O caminho real, agora com dois pontos de chamada

* **Boot/deploy:** `manage.py ensure_audit_partitions`, chamado logo após `migrate_schemas` —
  `scripts/migrate_schemas.sh` e `docs/DEPLOY.md` (não `CoreConfig.ready()`, que roda também em
  `migrate`/`makemigrations`/todo management command e tocaria o banco antes da própria migração
  poder rodar).
* **Diário:** Celery Beat (`core.ensure_audit_partitions`, migration 0045, `django_celery_beat`)
  — cobre o mês virando sem que um deploy aconteça no meio.
* **Rede de segurança com alarme:** a DEFAULT continua aceitando qualquer linha (nenhuma escrita
  de auditoria pode ser recusada — invariante da 020, intacta). Mas agora
  `apps.core.partitioning.default_leaf_row_counts()` é consultada a cada rodada de
  `ensure_audit_partitions`, e uma contagem não-zero vira `logger.warning(...)` — a partir de
  agora isso significa **partição faltando**, não operação normal.

## Consequências

* `TenantAuditRetention` — nova tabela, sem dado a migrar (migração 0044).
* `purge_audit_logs` não lê mais nenhuma Django setting para decidir *quando* ou *se* pode
  expurgar; resolve os dois por tenant, com fallback documentado para tenant sem linha.
* A trava de exportação fria da ordem 020 (`drop_partition(..., cold_export_receipt=...)`)
  continua inteira e é ortogonal a esta decisão: retenção decide *quando* pode tentar; o recibo
  decide *se* pode, de fato, dropar.
* Ligar o expurgo em qualquer ambiente real (inclusive staging) é uma decisão fora desta ordem —
  aqui só o mecanismo e o número ficam prontos; a decisão de acionar por cliente é operacional e
  posterior.
* `apps.core.management.commands.ensure_audit_partitions` (novo) — idempotente, chamado no
  boot/deploy e diariamente via Celery Beat (migration 0045) — é o que torna a retenção
  não-decorativa: sem ele, nenhuma escrita real jamais chegaria a uma partição dedicada, e o
  expurgo por tenant nunca teria o que derrubar (ver Emenda acima).
* `apps.core.audit_partition_backfill` + `manage.py backfill_audit_partitions` (novo,
  `--dry-run` padrão) — catch-up único para linhas que já caíram em alguma DEFAULT antes de
  `ensure_audit_partitions` existir. Medido e provado em banco descartável na lab (ver relatório
  de execução da ordem); rodar de verdade em staging/produção segue o plano de lock acima e é
  decisão operacional posterior, fora desta ordem.
