<!-- maestro-order v1
id: 020
ts: 2026-09-18T06:57:04-03:00
epoch: 1789725424
head: 7372273d188bcd5dad915938530b2e1756d24ccf
branch: order/020-auditlog-retencao
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 020 — core_auditlog ganha mecanismo de retencao: particao por tempo, expurgo configuravel e isolamento por tenant

> **Direção:** INTENT v5, **Prioridade 1 — "Isolamento entre tenants antes de qualquer
> feature. Schema-per-tenant é o produto, não a infra: um vazamento entre clínicas encerra
> o negócio"** — e **Prioridade 5** (LGPD como critério de aceite). Precede a ordem 019 por
> decisão do Imediato: não se acrescenta volume permanente a tabela que ninguém poda.

## O que a medição mostrou

`core_auditlog` é a única tabela do sistema que cresce para sempre, e é a que menos
governança tem. Medido em 17/09 na lab, no banco de staging:

```
schema                public          apps.core esta em SHARED_APPS
tabela                uma so          para TODOS os tenants; a coluna e schema_name
expurgo               NENHUM          procurado no codebase; so AIScribeSession tem retencao
indices               8               oito escritas de indice por linha inserida
bytes por linha       869             medido; user_agent tem 13 chars porque quem chama e
                                      cliente de API. Com navegador real passa de 200
linhas hoje           603             em 57 dias de lab (13 com atividade)
```

**O isolamento por tenant é a parte grave, e não é sobre volume.** A tabela está no schema
compartilhado. O INTENT põe schema-per-tenant como *o produto*, não como detalhe de infra —
e a trilha de auditoria, que é o registro do art. 37 da LGPD, mora fora dele. Encerrar
contrato com uma clínica hoje significa `DELETE ... WHERE schema_name = ...` numa tabela
que também guarda a auditoria de todas as outras.

**A projeção que vai ao Capitão**, para ele decidir o prazo: a ordem 019 propõe ligar
trilha em leitura de lista e em sete actions de prontuário. Só as telas que pollam — se um
dia forem auditadas — dariam ordem de **10 mil linhas por dia por tenant**; a ~1 KB por
linha isso é **~3,6 GB por ano por tenant**, somando entre clínicas por causa do schema
compartilhado. Este número é insumo da decisão dele, não um prazo que esta ordem escolhe.

## Os três limites do Imediato, e como cada um vira código

**1. Entrega o MECANISMO, não o prazo.** Nenhum número de dias nasce decidido aqui.
`AUDIT_LOG_RETENTION_DAYS` existe, é configurável, e o valor de fábrica é `None`. Quem
escolhe o número é o Capitão, com a medição acima na mão.

**2. Nenhum apagamento roda em staging ou prod sem ordem do Imediato.** Isto não pode ser
promessa em documento — tem de ser difícil de disparar por acidente:

* nenhuma migration registra tarefa periódica de expurgo. A migration cria o mecanismo e
  **não** agenda nada;
* o expurgo é comando explícito, e **recusa rodar** sem exportação fria provada (ver
  §Emenda) nem sem `AUDIT_LOG_PURGE_ENABLED = True`
  **e** `AUDIT_LOG_RETENTION_DAYS` preenchido. Faltando qualquer um, sai com erro nomeando
  o que falta — nunca apaga "por padrão razoável";
* `--dry-run` é o comportamento padrão do comando: sem flag explícita de execução, ele
  **relata** o que removeria e sai 0 sem tocar em nada;
* `settings/staging.py` e `settings/production.py` fixam `AUDIT_LOG_PURGE_ENABLED = False`,
  com o motivo escrito ao lado. Ligar ali é ato deliberado, visível em diff.

**3. O padrão de fábrica é reter, não expurgar.** Teste que reprova se isso mudar:
instalação limpa, tarefa chamada, **zero linhas removidas** — e a razão pela qual não
removeu vem nomeada. Um default que apaga é o tipo de regressão que ninguém revisa.

## Emenda do Capitão — a guarda longa sai do banco

**Duas camadas.** Quente no Postgres por uma janela curta; **frio em arquivo cifrado fora
do banco** pelo resto do prazo. O Postgres deixa de ser arquivo morto e volta a ser o que
ele faz bem: a janela operacional.

Com isso **o expurgo deixa de ser só `DROP PARTITION`**. Vira uma sequência, e o `DROP` é o
último passo, condicionado aos anteriores:

1. **exportar a partição** em **formato estável** — texto delimitado ou JSONL, **nunca**
   `pg_dump` binário. Isto tem de abrir daqui a vinte anos, em outra versão maior do
   Postgres, possivelmente sem Postgres nenhum. Formato acoplado à versão do servidor não
   é arquivo morto, é bomba-relógio;
2. **checksum do conteúdo em claro**, gravado antes de cifrar, para que a conferência
   depois da decifragem prove o dado e não só o envelope;
3. **cifrar reusando o caminho que o projeto já tem** para backup (`scripts/backup.sh` e o
   drill de restauração) — **não invente esquema novo nem gestão de chave nova**;
4. **manifesto** ao lado do arquivo: contagem de linhas, faixa de `created_at`,
   `schema_name`, sha256 do claro, versão do formato, versão da ferramenta, carimbo de
   tempo;
5. **restauração provada**: decifra, restaura em tabela de rascunho e **compara com a
   partição viva**, linha a linha. Só passa com igualdade de contagem e de conteúdo;
6. **controle negativo**: provar que a conferência sabe REPROVAR — arquivo adulterado de
   propósito tem de ser recusado, e a recusa tem de nomear o motivo. Verificação que nunca
   viu vermelho não é verificação, é cerimônia. É o mesmo crivo que a ordem 015 aplicou ao
   truststore vazio;
7. **só então `DROP PARTITION`.**

**Sem exportação provada, o `DROP` recusa** — e recusa nomeando qual passo faltou. Esta é a
trava principal da emenda: não existe caminho em que uma partição suma sem que exista,
antes, um arquivo frio verificado.

O que **não** muda: o prazo continua sendo decisão do Capitão, e o mecanismo inteiro
continua **desligado de fábrica**. Exportar também não roda sozinho.

**Onde o arquivo frio mora:** disco local, ao lado do que o `backup.sh` já produz. Offsite
só a partir da produção e em nuvem — INTENT §Limites e ordem 004, adiada por decisão do
Capitão. Não reabra isso aqui.

## Destino frio — decisão do Capitão: S3 Glacier Flexible, São Paulo

**Cifrado por nós ANTES de subir.** A chave é nossa; a da AWS não entra. SSE do provedor,
se usada, é camada extra por cima — nunca a única. O objeto que sai daqui já sobe ilegível
para quem hospeda.

**Um objeto por partição**, com manifesto e checksum — o manifesto sobe junto, como objeto
próprio, para que o arquivo seja conferível sem o banco de origem.

**Credencial que só grava.** `s3:PutObject` sem `s3:DeleteObject`, sem
`s3:BypassGovernanceRetention`, sem `PutObjectLegalHold`. Bucket com **versionamento** (o
Object Lock exige) e **Object Lock em modo compliance** pelo prazo escolhido.

**Drill que baixa, decifra e confere contagem contra o manifesto.**

**Nada vai ao ar antes de a conta AWS existir:** o destino é configurável, e o alvo de
teste é local.

### Três consequências que este destino fixa, e que mudam a ordem das operações

**1. Compliance mode é irreversível, e isso inverte a prioridade da verificação.** Em modo
compliance ninguém apaga antes do prazo — nem a raiz da conta. Retenção pode ser
aumentada, nunca reduzida. Logo, **objeto errado subido é objeto pago e inapagável pelo
prazo inteiro**. A verificação tem de acontecer **antes** do upload, não depois:

```
exportar -> checksum do claro -> cifrar -> decifrar e conferir LOCALMENTE
         -> só então subir -> conferir o remoto -> só então DROP
```

Subir para depois validar é o caminho que transforma um bug de exportação em vinte anos de
lixo cifrado e faturado.

**2. Glacier Flexible não devolve objeto de forma síncrona.** Recuperação é pedido
assíncrono: Expedited em 1–5 min, Standard em 3–5 h, Bulk em 5–12 h. Um drill escrito como
"baixa e confere" **não funciona** contra Glacier — ele precisa de pedido de restauração,
espera e coleta. O drill tem de nascer com esse ciclo, senão passa no alvo local e quebra
no dia em que valer.

**3. "Credencial que só grava" é afirmação até alguém provar o vermelho.** O teste tem de
mostrar que a credencial de escrita **falha ao tentar apagar**, e que o Object Lock
**recusa** a remoção — não basta ler a política e concordar com ela. Isso é provável sem
conta AWS: **MinIO na lab** fala o protocolo S3 e suporta versionamento e object lock. O
caminho S3 se prova ali; o alvo local cobre o resto.

**Sem isso, o caminho S3 é código que nunca rodou** — e vai estrear no dia em que a
primeira partição for apagada, que é o pior dia possível para estrear.

## O mecanismo

**Partição por tempo (RANGE em `created_at`), subparticionada por tenant (LIST em
`schema_name`).** Duas propriedades que uma tabela plana não dá:

* **expurgo vira `DROP PARTITION`, não `DELETE`.** `DELETE` em massa numa tabela com 8
  índices gera bloat e vacuum longo justamente na tabela que precisa estar sempre
  disponível para escrita. `DROP` é DDL, instantâneo, e não deixa espaço morto;
* **offboarding de clínica vira DDL de uma partição.** Encerrar contrato deixa de ser
  `DELETE` varrendo a auditoria de todo mundo e passa a ser derrubar o que é daquele
  tenant — que é o que o INTENT §Prioridade 1 exige da trilha tanto quanto dos dados.

Criação de partição futura é rotina agendada e **idempotente**: partição que já existe não
é erro. Uma partição `DEFAULT` recebe o que não casar com nenhuma faixa — linha de
auditoria **nunca** pode ser recusada por falta de partição. Se o `AuditLog` falhar, a
leitura que ele auditava já aconteceu; perder a trilha é pior que qualquer custo.

## Como isto é provado, e o que NÃO conta como prova

A migração converte uma tabela existente. Prova exigida:

* **contagem antes e depois, igual**, e amostra conferida linha a linha — nenhuma linha de
  auditoria pode sumir na conversão. Perder trilha para instalar mecanismo de retenção
  seria o resultado mais absurdo possível;
* **teste de expurgo com o relógio fixado**: linhas dentro e fora da janela, e a asserção
  de que só as de fora saem — e só com as duas configurações ligadas;
* **teste do padrão de fábrica**: sem configuração, nada sai;
* **teste de isolamento**: expurgo de um tenant não toca linha de outro;
* **teste da `DEFAULT`**: inserção fora de qualquer faixa é aceita, não recusada;
* **exportação e volta**: exporta uma partição, decifra, restaura e compara com a viva —
  contagem e conteúdo iguais;
* **controle negativo da exportação**: arquivo adulterado é **recusado**, com o motivo
  nomeado;
* **o `DROP` recusa sem exportação provada**, e o teste prova a recusa, não só o caminho
  feliz;
* a migração roda em banco descartável na lab. `--dry-run` primeiro, com o plano impresso.

**Não conta como prova:** rodar em staging. A ordem não autoriza tocar em staging nem em
prod — nem a migração, nem o expurgo. Quando o mecanismo estiver provado em banco
descartável, quem decide o cutover é o Imediato.

## Fora desta ordem

O número de dias de retenção (é do Capitão). Ligar o expurgo em qualquer ambiente. Mover
`core_auditlog` para os schemas de tenant — é mudança de arquitetura muito maior, e a
subpartição por `schema_name` entrega o isolamento operacional sem ela; se depois se
decidir mover, a subpartição é o caminho mais curto para lá, não um desvio.

Nada de frontend. Nenhuma mudança em `AuditReadMixin` — a 019 é que mexe nele, e vem
depois desta.

## Contrato de execução
- Trabalhe APENAS no branch `order/020-auditlog-retencao`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-20 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 020` (você não fecha a própria ordem).
