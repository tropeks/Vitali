<!-- maestro-order v1
id: 008
ts: 2026-09-13T00:07:54-03:00
epoch: 1789268874
head: 3bb9a5357a116b112804beb7bfeebeb82d7ad6ef
branch: order/008-fechamento-de-lote
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 008 — Prioridade 2: percorrer a cadeia de receita ate o fechamento do lote pelo caminho real

## Contexto

`.maestro/INTENT.md` v5, §Prioridades item 2: *"Receita destravada antes de escopo novo. O
caminho guia TISS válida → lote → faturamento tem precedência sobre qualquer módulo
adicional."* É esta seção que autoriza a ordem.

A ordem 006 percorreu guia → lote → valor, mas parou numa **soma impressa**:
`verify_revenue_chain.py:185` faz `total = sum(...)` em memória, escreve o número na saída e
nunca fecha nada. Medido em 13/09 na lab, os lotes que a caminhada produziu:

```
2026090001 | open | 0.00      2026090002 | open | 0.00
```

Não é que o sistema não saiba fechar — `TISSBatchViewSet.close`
(`backend/apps/billing/views.py:1345-1454`) agrega `Sum("total_value")` e grava `status`,
`closed_at` e `total_value`. A prova do passo 3 da 007 fechou dois lotes por lá, com
R$ 100,00 gravado. O problema é que essas ~110 linhas de regra vivem **dentro de uma view**,
devolvendo `Response` de dentro do `atomic()` — nenhum outro caminho consegue reusá-las.

Resultado: "faturamento" da Prioridade 2 está provado como valor **apurável**, não como
estado **persistido**. Esta ordem fecha essa distância.

## Abordagem

Extrair o fechamento para service, no padrão que o `billing` já usa
(`services/aih_lifecycle.py`: função `@transaction.atomic`, argumentos por palavra-chave,
`select_for_update`, exceção tipada, devolve o objeto). A view passa a traduzir exceção em
HTTP; o comando chama a mesma função.

1. **Novo `backend/apps/billing/services/batch_lifecycle.py`** — `fechar_lote(*, lote, actor)
   -> TISSBatch` com o corpo atual da view, sem nenhum `Response`. Três exceções tipadas para
   os três desfechos que a view distingue hoje: `LoteNaoAberto` (→400), `GlosaBloqueante`
   carregando o payload por guia (→409) e `LoteAlteradoDuranteFechamento` (→409). A
   `DjangoValidationError` da dupla apresentação continua subindo como está.
2. **`backend/apps/billing/views.py`** — `close` vira chamada ao service mais o `except` que
   mapeia cada exceção para o **mesmo status e o mesmo corpo de hoje**. Nenhuma mudança de
   contrato HTTP: os comentários que explicam o lock, o escopo por `evaluated_ids` e a
   reafirmação do conjunto de guias vão junto para o service — cada um deles registra um bug
   que já aconteceu.
3. **`backend/apps/core/management/commands/verify_revenue_chain.py`** — o passo 5 deixa de
   imprimir uma soma e passa a chamar `fechar_lote`, relatando `status` e `total_value` lidos
   do banco depois do fechamento. O `--dry-run` continua revertendo tudo.

## Teste que falha antes

`backend/apps/core/tests/test_verify_revenue_chain_closes_batch.py`: roda a cadeia e afirma
que o lote terminou `status="closed"` com `total_value == Decimal("100.00")` e `closed_at`
preenchido. Hoje falha — o lote fica `open` em `0.00`. Commit do teste sozinho primeiro, como
nas ordens 006 e 007.

A rede de proteção da extração são os testes que já existem: **20 asserções sobre o
fechamento** em `backend/apps/billing/tests/test_billing.py` e
`backend/apps/billing/tests/test_glosa_safety.py`. Elas têm de passar **sem edição** — se
alguma precisar mudar, o contrato mudou e a extração está errada.

## Prova

1. Par teste-antes/teste-depois, medido em container na lab (docker é negado ao meu usuário
   nesta máquina), com os sha256 dos logs no ledger.
2. Os quatro verificadores do gate rodados antes do push: `ruff check`, `ruff format --check`,
   `lint-imports`, `mypy`.
3. CI verde nos cinco jobs sobre o tip.
4. Em staging, a cadeia rodada por comando deixando **o lote `closed` com R$ 100,00 gravado** —
   lido do banco, não da saída do comando. Recibo `order-8`.

## Risco, e o que o contém

Mexe no caminho de fechamento que a operação usa — `.maestro.yaml` põe billing e TISS sob
revisão de especialista. Contenção: o comportamento HTTP não muda, as 20 asserções existentes
não se tocam, e a extração é movimento de código, não reescrita de regra. Se algum teste de
billing exigir edição, paro e reporto em vez de ajustar o teste.

## Fora de escopo

Não fecha lote automaticamente em lugar nenhum (nem task Celery, nem signal); não mexe na
cunha de glosa; não altera o payload do 409; não toca nos lotes `2026090001` e `2026090002`
que já estão em staging — eles ficam como registro do estado anterior.


## Contrato de execução
- Trabalhe APENAS no branch `order/008-fechamento-de-lote`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-8 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 008` (você não fecha a própria ordem).

## Aprovação

Aprovada pelo Imediato em 13/09, com as condições dele, transcritas:

> extração para service no padrão do `aih_lifecycle`, contrato HTTP intacto, 20 asserções
> existentes sem edição — **se alguma precisar mudar, pare e reporte**. Prova = lote
> `closed` com R$ 100,00 **lido do banco**.

A terceira condição é a que decide: as asserções existentes são o oráculo da extração. Se
uma delas exigir edição, o contrato mudou e a extração está errada — e aí o certo é parar,
não ajustar o teste até ficar verde.
