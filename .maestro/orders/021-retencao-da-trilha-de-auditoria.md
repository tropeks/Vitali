<!-- maestro-order v1
id: 021
ts: 2026-09-22T05:43:32-03:00
epoch: 1790066612
head: 40d60440bb38ce2e73393b568f8bc56f4635eee5
branch: order/021-retencao-20-anos
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 021 — Retencao da trilha de auditoria: 20 anos por decisao do Capitao, configuravel por tenant, expurgo desligado de fabrica

> **Direção:** INTENT v5, **§Prioridade 5** (compliance como critério de aceite) e
> **§Prioridade 1** (isolamento entre tenants é o produto). Continuação da ordem 020,
> que entregou o mecanismo; esta põe o número que faltava.

## A decisão, e de onde ela vem

**Prazo de guarda da trilha de auditoria = 20 anos**, igual ao prontuário. Decisão do
Capitão em 22/09/2026, registrada na Ponte (`01M325GP8W497HQWJ3GY55JPP9`, escolha
`vinte_anos`). Base legal:

* **Res. CFM 1.821/2007, art. 8** — prazo mínimo de 20 anos para guarda dos prontuários;
* **Lei 13.787/2018, art. 6** — 20 anos a contar do último registro, para prontuário
  eletrônico.

**Expurgo DESLIGADO de fábrica, ligado por cliente.** A 020 já entregou o mecanismo com
essa postura; esta ordem a mantém e a move para o nível certo — **por tenant**, não
global.

## O que a decisão não fixava, e ficou decidido no plano (aprovado 22/09)

**1. Onde mora a configuração.** `FeatureFlag` é booleano puro e não carrega número.
O precedente do projeto é `TenantAIConfig` — OneToOne de configuração por tenant. Esta
ordem cria `TenantAuditRetention` no mesmo padrão, mantendo `core.Tenant` enxuto.

**2. A unidade é MÊS, não dia.** A 020 entregou `AUDIT_LOG_RETENTION_DAYS`, mas **o que
se expurga é partição mensal**. Em dias, 20 anos oscila entre 7.305 e 7.306 conforme
bissextos, e a borda vira bug que ninguém reproduz; em meses são **240, exato**, e a
unidade do prazo passa a ser a mesma unidade do mecanismo. A migração de unidade é feita
agora, enquanto o expurgo nunca rodou em lugar nenhum e não existe dado a reinterpretar.

**3. "Ligado por cliente" é opt-in explícito.** O padrão de fábrica continua sendo
**reter**: retenção 240 meses **e** expurgo desligado. Ligar exige ato deliberado por
tenant, visível no banco e em diff.

## O trabalho

1. **ADR novo.** `docs/adr/` **não existe** — crie o diretório e o `ADR-0001` desta
   decisão: base legal, data, quem decidiu, alternativa descartada, e a **estimativa de
   armazenamento: ~3,6 GB/ano/tenant** (medida na 020: ~10 mil linhas/dia/tenant se as
   telas de polling forem auditadas, ~1 KB por linha, somando entre clínicas porque
   `apps.core` está em `SHARED_APPS` e `core_auditlog` é tabela única no schema `public`).
2. **`TenantAuditRetention`** — OneToOne com `core.Tenant`, no padrão de `TenantAIConfig`:
   `retention_months` (default **240**) e `purge_enabled` (default **False**). Migration
   nova, sem dado a migrar.
3. **O comando de expurgo da 020 passa a resolver prazo e permissão POR TENANT**, não por
   setting global. Tenant sem configuração usa o default de fábrica — 240 meses, expurgo
   desligado — e **nunca** apaga por omissão.
4. **A trava da 020 continua inteira:** `drop_partition(name, *, cold_export_receipt)`
   exige recibo de exportação fria verificado. Esta ordem não afrouxa isso em nenhum
   caminho; retenção decide *quando pode*, o recibo decide *se pode*.

## Emenda do Imediato, 22/09 — a 020 entregou o mecanismo sem ninguém chamá-lo

**"Não carimbo 20 anos em cima de expurgo inerte."** Medido em banco limpo, com a
migration da 020 aplicada:

```
AuditLog.objects.create(...)   -> cai em core_auditlog_default_default
ensure_tenant_partition        -> NAO e chamada em nenhum lugar do codigo de producao
                                  (so num comentario e nos testes; sem rotina agendada)
```

O expurgo por tenant só derruba a **folha dedicada**, que nunca é criada. A retenção de 20
anos seria decorativa: os testes passam porque a fixture cria a folha à mão, e o sistema
real nunca produz essa condição.

**Duas armadilhas medidas, que definem COMO consertar:**

1. **A DEFAULT trava a criação da partição correta.** Com linha na DEFAULT, criar a
   partição do mês correspondente falha:
   `IntegrityError: updated partition constraint for default partition
   "core_auditlog_default" would be violated by some row`. Quanto mais tempo passa, pior —
   a saída exige tirar o dado da DEFAULT primeiro.
2. **O trigger append-only recusa `DELETE`:** `AuditLog is append-only (CFM 1.821/2007):
   DELETE blocked`. Então mover linha para fora da DEFAULT **não** é `INSERT…SELECT` +
   `DELETE`; exige desabilitar o trigger dentro da migração, com a tabela travada, e
   reabilitá-lo — e é exatamente por isso que o plano de lock precisa estar escrito.

### O escopo acrescentado

1. **Rotina idempotente** que pré-cria a partição do **mês corrente e do seguinte** para
   cada tenant, com as funções que já existem (`ensure_month_partition`,
   `ensure_tenant_partition`), chamada **no caminho real**: agendada **e** no boot.
   **Cuidado com o boot:** `AppConfig.ready()` roda também em `migrate`, `makemigrations` e
   em todo management command — tocar o banco ali quebra a própria migração. Use um
   management command dedicado, chamado pelo entrypoint **depois** do migrate, mais a
   tarefa agendada.
2. **Teste que prova que uma escrita real de `AuditLog` cai em folha dedicada**, não na
   DEFAULT — asserção sobre `tableoid::regclass`, com a escrita feita pelo ORM, não por SQL
   preparado pela fixture.
3. **Migração de dados** que move o que já está na DEFAULT para as folhas **antes** de criar
   as partições, com **contagem de linhas e tempo medidos** e o **plano de lock escrito no
   ADR** para o caso de clínica em operação. Hoje são poucas linhas; o ADR tem de dizer como
   se faz quando não forem.
4. **A DEFAULT continua como rede de segurança** — linha de auditoria nunca pode ser
   recusada. Mas passa a ter **alarme**: log/métrica quando qualquer linha cair nela, porque
   a partir daqui isso significa **partição faltando**, não funcionamento normal.

### O que vai no ADR, além da decisão

Registre que **a 020 entregou o mecanismo sem ninguém chamá-lo**, e a lição:
**aceite de mecanismo exige prova no caminho real, não só na fixture.** Um teste que
constrói à mão a condição que o sistema nunca produz mede a si mesmo.

**Ambiente:** staging apenas. **Produção vai por ship com gate** — não por esta ordem.

## Prova exigida

* **padrão de fábrica não expurga**: instalação limpa, tarefa chamada, **zero** linhas
  removidas, com a razão nomeada;
* **o prazo é respeitado**: tenant com expurgo ligado só derruba partição **além** dos
  seus 240 meses — partição dentro do prazo permanece, e o teste prova a permanência,
  não só a remoção;
* **isolamento**: tenant A com expurgo ligado **não toca** linha de tenant B, nem quando
  as duas vivem no mesmo mês — é a Prioridade 1 da direção, e é o motivo de a 020 ter
  subparticionado por `schema_name`;
* **`--dry-run` continua sendo o padrão** do comando;
* **o `DROP` continua recusando sem recibo de exportação fria**, e o teste prova a recusa.

Tudo em **banco descartável na lab**. Recibo no tip do branch.

## Fora desta ordem

Ligar o expurgo em qualquer ambiente — **produção e staging não são tocados**, nem
migração nem expurgo. Backend S3/Glacier (ordem própria, precisa de `boto3` e MinIO).
`DROP` da `core_auditlog_pre020`, que segue de pé até aceite explícito do Imediato.

**O `intent --bump` NÃO é desta ordem nem do executor**: o cabeçalho do INTENT diz que a
direção é carimbada pelo Capitão. O ADR fica pronto e a linha para o INTENT vai no
relatório, para ele carimbar.

## Contrato de execução
- Trabalhe APENAS no branch `order/021-retencao-20-anos`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-21 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 021` (você não fecha a própria ordem).
accepted_at: 2026-09-22T09:14:17-03:00
accepted_session: desconhecido
accepted_tree: 74d38b41da5744ac32f0a07a5cf8481dae953a7e
accepted_intent: 5
