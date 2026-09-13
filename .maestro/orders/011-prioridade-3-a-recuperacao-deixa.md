<!-- maestro-order v1
id: 011
ts: 2026-09-13T07:29:37-03:00
epoch: 1789295377
head: 6dd368545fe44a4e322c72ddb38e3230a1c32846
branch: order/011-drill-noturno
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 011 — Prioridade 3: a recuperacao deixa de ser prova de um dia e vira sinal diario

## A medição, antes do plano

Comparei o que o INTENT v5 promete nas Prioridades 1, 3 e 5 com o que existe na lab.

**Prioridade 1 (isolamento provado por teste no CI) — honrada.** `ENFORCE_TENANT_MEMBERSHIP=True`
em `.env.staging`; 279 arquivos de teste usam `TenantTestCase`/`tenant_context`;
`test_tenant_membership.py` cobre inclusive reivindicação de schema alheio
(`test_get_user_rejects_foreign_schema_claim`); o job `Backend — Tests` roda `pytest` sobre a
suíte inteira. Não é o buraco.

**Prioridade 5 (compliance como gate) — difusa, não é buraco de engenharia.** MFA aparece só
como configuração em `settings/base.py`; `AIDPAStatus` existe com consentimento e testes
(`apps/ai/consent.py`); não há gate de compliance no CI. É programa de GA (DPA, assinatura
ICP, política de privacidade revisada), com decisão jurídica e de produto dentro — não cabe
numa ordem de engenharia agora.

**Prioridade 3 (recuperação provada) — este é o buraco, e é nítido:**

```
backups                    produzidos toda noite (último: 13/09 02:00, 25 MB)
drill de restore           provado UMA vez, em 12/09, contra o dump daquele dia
métrica de sucesso         vitali_backup_last_success_timestamp_seconds É escrita
regra VitaliBackupStale    existe em docker/observability/alerts.yml
quem avalia a regra        NINGUÉM — a pilha de observabilidade não roda na lab
healthcheck do db-backup   nenhum (0 ocorrências em docker-compose.staging.yml)
alerta em scripts/backup.sh nenhum — sem email, sem webhook
```

**Se o backup parar hoje à noite, ninguém descobre.** É a mesma forma do defeito que originou
a ordem 003 — lá o pipeline nunca tinha produzido um backup e o `crond` nem disparava, e só
se soube porque alguém foi olhar. O INTENT §Prioridades 3 diz *"Backup que nunca foi
restaurado não é backup"*; um backup que ninguém confere é da mesma família. E a prova de
12/09 não diz nada sobre o dado de hoje, que mudou muito nas ordens 006–010.

Autoriza a ordem: **INTENT v5 §Prioridades 3** e **§Limites** ("sinal verde tem que
significar verde" — aqui não há sinal nenhum).

## Abordagem — decisão sua: drill noturno **mais** sinal contínuo

1. **`scripts/run_restore_drill.sh` passa a escrever métrica.** No padrão que
   `scripts/backup.sh:177` já estabeleceu e pela mesma disciplina: escrita **só ali, e só
   depois** de o drill passar E a limpeza ser verificada — métrica gravada antes seria pior
   que alerta nenhum, porque afirmaria restauração que não houve.
   `vitali_restore_drill_last_success_timestamp_seconds` e
   `vitali_restore_drill_duration_seconds`, no mesmo `/backups/metrics` do backup.

2. **O drill roda toda noite, às 03:00** — depois do backup das 02:00. Entra por
   `scripts/install_drill_cron.sh` versionado (crontab do host, não serviço em contêiner: o
   drill sobe contêineres, e dar o socket do Docker a um serviço seria escalada de
   privilégio para economizar uma linha de cron). O script é idempotente e imprime a entrada
   que instalou.

3. **`db-backup` ganha healthcheck** lendo a métrica que ele já escreve: falha quando o
   último backup tem mais de 26 h. Backup parado passa a ser **vermelho em `docker ps`**, sem
   depender de Prometheus.

4. **`scripts/smoke_test.sh` ganha duas checagens** (11ª e 12ª): backup com menos de 26 h, e
   **drill com menos de 30 h e verde**. Drill velho ou vermelho **reprova o smoke** — sua
   condição. Entram no contador de pulos que a ordem 007 criou: se a métrica não existir, é
   `skip` contado e saída 2, nunca verde silencioso.

5. **Higiene e isolamento, as suas outras duas condições.** O script já copia o **cifrado**
   para um `WORKDIR` efêmero, restaura em contêiner descartável e verifica a limpeza; a ordem
   011 acrescenta a **prova `find` explícita** de que não restou texto claro (o padrão da 003)
   como pré-requisito da métrica, e um **guard** que aborta se o alvo do restore resolver para
   o postgres de staging — hoje isso é verdade por construção, e vira verdade verificada.

## Teste que falha antes

- `test_drill_metric_only_after_clean.py` (pytest sobre o script, via `bash`): com a limpeza
  falhando, a métrica **não** é escrita; com o drill passando e a limpeza verificada, é
  escrita com timestamp. Hoje o arquivo de métrica não existe — falha por ausência.
- `scripts/smoke_test.sh`: rodar com métrica ausente/velha **reprova** (saída ≠ 0) e nomeia
  qual das duas falhou. Hoje passa 10/10 sem olhar backup nenhum.
- O guard de staging: apontar o drill para o postgres de staging aborta antes de tocar o
  banco.

## Prova

1. Par antes/depois medido na lab, sha256 dos logs no ledger.
2. Gate completo antes do push: `ruff check`, `ruff format --check`, `lint-imports`, `mypy`,
   `bash -n` nos scripts, `tsc`/`next lint` se o frontend for tocado (não deve ser).
3. CI verde nos cinco jobs no tip.
4. Em staging, **lido do disco e do `docker ps`**: o drill noturno rodando por comando contra
   o dump de hoje, a métrica escrita, `db-backup` `healthy`, e o smoke **12/12**. Depois,
   envelhecendo a métrica artificialmente, o smoke **reprova** nomeando a checagem — o sinal
   provado nos dois sentidos, que é o que a 007 ensinou a exigir.
5. A prova `find` de que não restou texto claro, e o sha256 do cifrado copiado registrado
   antes da remoção — como na ordem 003.
6. Recibo `order-11` como **última** ação no tip.

## Risco

O drill noturno restaura ~25 MB num postgres efêmero toda madrugada. Se ele falhar em
silêncio, o próprio smoke passa a acusar — é justamente o ponto. O healthcheck novo pode
deixar `db-backup` vermelho se a métrica não existir ainda na primeira noite; o plano inclui
escrever a métrica na primeira execução manual, antes de ligar o cron, para não nascer
vermelho por vacuidade.

## Fora de escopo

Não sobe a pilha de observabilidade (Prometheus/Grafana) — a decisão foi sinal no healthcheck
e no smoke, sem novo serviço. Não mexe em `restore_test.sh`, o drill canônico. Não toca em
offsite (ordem 004, encerrada como NÃO AGORA). Não altera `backup.sh` além do que for
necessário para a métrica do drill conviver com a dele.


## Contrato de execução
- Trabalhe APENAS no branch `order/011-drill-noturno`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-11 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 011` (você não fecha a própria ordem).

## Aprovação

Aprovada pelo Imediato em 13/09, nas palavras dele:

> métrica escrita só depois do drill passar **E** da higiene verificada; cron no host (não
> socket do Docker em contêiner — certo); healthcheck do `db-backup` por frescura; smoke com
> as duas checagens contadas como `skip` quando faltar métrica. **Prova = uma noite real:**
> backup 02:00, drill 03:00, smoke verde de manhã com as duas checagens. Recibo como última
> ação.

A prova de uma noite real impõe prazo: o recibo `order-11` só pode ser gravado na manhã
seguinte à implantação. Implantar e armar o cron não é prova; a prova é o que a noite deixou.

---

## Resultado

### O par, medido em container na lab

```
ANTES  (o teste sozinho, sem o script)        5 failed
DEPOIS (1d6c83f)                              5 passed
gate    ruff check · ruff format --check · lint-imports · mypy (1057) · bash -n
```

`p011-antes.log` sha256 `e51b86c6…0001dc5ca` · `p011-depois.log` `b8dd70b4…d0e3b3528`.

**Meu primeiro teste estava fraco, e medir pegou.** Os quatro casos negativos afirmavam só
`returncode != 0`, então passavam **com o script ausente** — `bash` sai 127. Teste que fica
verde pelo motivo errado não prova nada, que é o defeito desta série inteira. Apertados para
exigir a recusa do portão (saída 1 com o motivo em `stderr`) e distinguir de chamada
malformada (saída 2).

### O ciclo, executado à mão

```
drill    exit 0 · 159s
         fase 1: restore_test.sh PASSOU contra vitali_20260913T020000Z.dump.gpg
         fase 2: inventário DIFERENTE — 24 linhas (escrita legítima em staging depois
                 do dump; relatado integralmente, não reprova sozinho, por desenho)
         limpeza: containers=0 · claros_tmp=0 · claros_work=0
         cifrado removido, sha256 cfcb9037… registrado antes
         métrica escrita e publicada no volume vitali-lab_backups
db-backup  healthy pelo healthcheck novo, exit=0, lendo a métrica real
smoke      12 passadas · 0 falhas · 0 puladas
```

### O sinal, provado nos DOIS sentidos

Verde quando deve não prova nada sozinho — foi a lição da ordem 007. Envelhecendo a métrica
do drill para 40 h:

```
✗ último drill de restore tem menos de 30h (got: 40h atrás, expected: <30h)
Results: 11 passed, 1 failed, 0 skipped     SMOKE EXIT=1
```

Reprova, e **nomeia a checagem**. Métrica restaurada em seguida.

### O que a medição me obrigou a mudar

A **primeira** execução do drill falhou na fase 2 — "postgres efêmero não ficou pronto" —
porque rodou no mesmo minuto de um `docker compose up --force-recreate`. Sozinha em seguida,
passou. Não é detalhe: um tropeço desses às 03:00 não deixaria métrica, a tolerância de 30 h
expiraria no meio da manhã seguinte, e o smoke ficaria vermelho **por barulho** — o que o
§Limites proíbe explicitamente.

Daí o retry único, dez minutos depois, com o comando repetido na própria linha do crontab
(`1da988b`). A repetição é feia e fica: retry DENTRO do drill contaminaria "o drill passou",
e um script gerado em disco ficaria fora do versionamento. Quem roda `crontab -l` vê a
política inteira.

### Um furo pego antes de rodar, não depois

O cron escreveria a métrica num caminho do host; o smoke a lê de **dentro** do contêiner de
backup, no volume. Não se encontrariam — e o "pulo contado" teria escondido isso atrás de uma
explicação plausível ("métrica ausente"). O drill agora publica a cópia no volume por
contêiner, no mesmo `metrics/` onde o `backup.sh` escreve a dele.

### Cron armado

```
0 3 * * * cd /srv/vulcan/apps/vitali && { bash scripts/run_restore_drill.sh … \
          || { sleep 600; bash scripts/run_restore_drill.sh … }; } >> drill/cron.log 2>&1
```

Instalado por `scripts/install_drill_cron.sh`, idempotente, marcado por comentário próprio.
O backup roda 02:00; o drill vem às 03:00.

### O que esta ordem NÃO fez

Não subiu Prometheus nem Grafana — a decisão foi sinal no healthcheck e no smoke, sem novo
serviço. As regras de `docker/observability/alerts.yml` seguem sem quem as avalie, e isso
continua aberto. Não tocou em `restore_test.sh`, o drill canônico. Não mexeu em offsite
(ordem 004, NÃO AGORA).
accepted_at: 2026-09-13T10:01:14-03:00
accepted_session: desconhecido
accepted_tree: 953be0d646b38187ce85d56f8bd17941eebd892d
accepted_intent: 5
