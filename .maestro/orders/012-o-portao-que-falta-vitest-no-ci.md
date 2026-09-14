<!-- maestro-order v1
id: 012
ts: 2026-09-14T08:38:44-03:00
epoch: 1789385924
head: 88e66504e55725bb78d097f292e1c38fac571a8c
branch: order/012-portao-que-falta
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 012 — O portao que falta: vitest no CI e a fase 2 do drill comparando contra o inventario do dump

## Contexto

Ordem do Imediato em 14/09, com a sequência delegada a mim:

> CI não roda vitest — 790 testes de frontend sem ninguém olhando é o mesmo defeito que a
> auditoria de leitura em 2 de 40 viewsets, só que no outro lado. Ponha vitest no CI, e no
> mesmo trabalho feche a segunda fase do drill noturno (comparação de inventário, não só fase
> 1) — **sinal que não compara não prova recuperação, prova que o script rodou.**

Autoriza: **INTENT v5 §Limites** ("sinal verde tem que significar verde") e **§Prioridades 3**
(recuperação provada).

### Medido antes de planejar

**(a) O CI não roda vitest.** `ci.yml` tem `Frontend — Lint & Types` (ESLint + `tsc`) e
`Frontend — E2E (Playwright)`. A suíte unitária — **172 arquivos, 790 testes** — não tem
portão nenhum. Verde hoje, medido em 13/09; nada garante amanhã.

**(b) A fase 2 do drill compara contra a coisa errada.** Duas camadas de problema:

1. A linha do cron instalada pela ordem 011 não passa `--reference`/`--inventory-sql`, então
   a fase 2 sai **"nao executada"** — medido no ciclo real de 14/09.
2. Pior: mesmo quando passa, a referência é `migracao/inventario-LAB.txt`, **um arquivo
   estático de 11/09**. Comparar o restore de hoje contra uma foto de três dias atrás diverge
   sempre — daí as "24 linhas divergentes" em toda execução, que o script corretamente
   **não** trata como reprovação, porque não pode. Uma comparação que nunca pode falhar não
   é comparação.

## Sequência — escolha minha, e a razão é economia de CI

**Primeiro a fase 2, depois o vitest.** A fase 2 é shell: verifica-se com `bash -n` e com
execução real na lab, sem gastar CI. O vitest é o item que **precisa** do CI para ser provado
— o portão novo só vale depois de rodar de verdade. Pondo-o por último, a única execução na
ponta prova as duas coisas, e prova a que importa: o portão novo funcionando.

## Abordagem

### (b) A fase 2 passa a comparar contra o inventário DO DUMP

1. **`scripts/backup.sh`** tira um snapshot de inventário imediatamente após o `pg_dump`,
   com o mesmo SQL que o drill usa, e o grava ao lado do artefato
   (`vitali_<carimbo>.inventario.txt`). É a única hora em que a foto e o dump descrevem o
   mesmo instante.
2. **`scripts/run_restore_drill.sh`** passa a preferir o snapshot do artefato escolhido sobre
   o `--reference` estático. Com ele, **divergência vira reprovação** — o dump não contém o
   que a origem tinha é exatamente a falha que um drill existe para achar. Sem ele (artefatos
   antigos), mantém o comportamento atual de relatar sem reprovar, dizendo por quê.
3. **`scripts/install_drill_cron.sh`** passa `--inventory-sql` na linha do cron, para a fase 2
   deixar de sair "nao executada".

### (a) vitest entra no CI — como passo, não como job novo

No job `Frontend — Lint & Types`, que já faz `npm ci`. Um job novo gastaria outro runner e
outro `npm ci` por nada, e a ordem de economia do Imediato vale. Fica logo após o `tsc`.

## Prova

1. Fase 2: execução real na lab contra o backup da noite, mostrando a comparação **passando**
   contra o snapshot do próprio dump; e uma execução com o snapshot adulterado, mostrando que
   **reprova** — sinal nos dois sentidos, como a ordem 007 ensinou a exigir.
2. vitest: **uma** execução de CI na ponta, com o job de frontend rodando os 790 testes.
3. `bash -n` e `ruff`/`mypy` locais antes do push; nenhum push em cascata.
4. Recibo `order-12` como última ação no tip.

## Fora de escopo

ICP, checklist jurídico e CBHPM/LOINC são mão do Capitão, por ordem expressa do Imediato —
esta ordem não entra neles. Também não sobe observabilidade nem mexe em `restore_test.sh`.


---

## Resultado — medido, 14/09

### O que a fase 2 comparava, e por que nunca podia reprovar

A referência era `migracao/inventario-LAB.txt`, **foto estática de 11/09 que nem estava
versionada**. Um restore de hoje diverge dela sempre — daí as "24 linhas divergentes" em toda
execução, que o script corretamente se recusava a tratar como reprovação. Comparação que não
pode falhar não prova recuperação: prova que o script rodou.

Agora `backup.sh` tira a foto no instante do `pg_dump`, ao lado do artefato — o único momento
em que foto e dump descrevem o mesmo estado — e o drill a prefere sozinho, derivando o nome do
próprio artefato. Divergência com foto presente **reprova**.

```
contra a foto do próprio dump     IDENTICO · exit 0
com a foto adulterada             exit 1, nomeando a linha divergente
```

### O defeito pré-existente que apareceu no caminho

`backup.sh` roda com `set -euo pipefail` e a retenção usa o glob `vitali_*.dump`, que **nunca
casa** com a cifra ligada (o texto claro é apagado logo após o gpg). Sob `pipefail` o `ls` que
falha vence o `tail`, a atribuição sai não-zero e o `set -e` mata o script **logo depois de a
métrica de sucesso já ter sido escrita**.

Raio medido, artefato a artefato:

| pergunta | medição |
|---|---|
| o `.gpg` saía íntegro? | **sim** — o `exit 1` é a última linha, depois de gpg, da remoção do claro e da métrica. 7 de 7 artefatos decifram e têm TOC legível (2.974 itens nos recentes) |
| o drill restaurou de cifrado? | **sempre** — 4 drills, todos `.dump.gpg`. O noturno de 14/09 03:00 restaurou o artefato das 02:00 da mesma noite, a execução que saiu 1: 269 migrations, 2 tenants, 4 pacientes em `demo` |
| quantos acumularam? | **8 no pico**, um acima de `KEEP_LAST=7`. 147 MB; disco da lab em 12% de 465 GB. A primeira execução consertada podou `vitali_20260911T230846Z.dump.gpg` |
| desde quando? | primeira execução afetada **11/09 23:08:46 UTC** — o primeiro backup cifrado que existiu. Defeito no código desde **13/06 (`d307f1e`)**, o commit que introduziu a cifra e trocou o glob único por dois |

O limite do sinal que isto expõe: o healthcheck e o smoke da ordem 011 diziam `healthy` por
cima de um script que saía 1, porque leem a métrica — escrita **antes** da linha que falhava.
Eles provam "existe backup recente e restaurável", não "o script terminou bem". O `crond` do
busybox não manda exit code a lugar nenhum.

### vitest ganhou portão, e o portão achou uma frouxidão

Entrou como passo no job de frontend que já existe (renomeado `Frontend — Lint, Types &
Unit`). Pôr sob portão expôs um teste instável — o de guia de internação esperava o cabeçalho
do painel, que renderiza na hora, e então afirmava o valor do `select`, que só chega depois do
fetch das opções. A asserção é a mesma; passou a ser aguardada. Suíte completa 3×: 790, 790,
790.

### Fechamento

```
CI em 624c41e            VERDE (uma execução, na ponta)
cron rearmado            a linha estava sem --inventory-sql; a fase 2 desta noite compara
```

## Contrato de execução
- Trabalhe APENAS no branch `order/012-portao-que-falta`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-12 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 012` (você não fecha a própria ordem).
