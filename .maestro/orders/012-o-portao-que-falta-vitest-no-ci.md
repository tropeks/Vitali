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


## Contrato de execução
- Trabalhe APENAS no branch `order/012-portao-que-falta`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-12 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 012` (você não fecha a própria ordem).
