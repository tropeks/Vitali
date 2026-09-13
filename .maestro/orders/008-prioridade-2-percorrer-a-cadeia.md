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

---

## Resultado

### O par, medido

Container descartável na lab, imagem que o CI fixa, `postgres:16-alpine` e `redis:7-alpine`
efêmeros. Docker é negado ao meu usuário na máquina de trabalho; a lab tem.

```
ANTES  (cdbc6a5, o teste sozinho)                    2 failed in 7.10s
       AssertionError: 'open' != 'closed'
       AssertionError: Decimal('0.00') != Decimal('100.00')
       e "erros XSD : 0" no stdout capturado — a cadeia percorreu inteira, a
       falha é o fechamento, não uma lacuna de fixtura
DEPOIS (4cf5b18)                                     5 passed
REDE   (asserções existentes, NENHUMA editada)     143 passed
       apps/billing/tests/test_billing.py + apps/billing/tests/test_glosa_safety.py
```

`antes.log` sha256 `9d7d8b88…5c1a6880` · `depois.log` `a36c1604…ac5e94e20` · `rede.log`
`eb62f1df…4583e31fdaf4b`. Ledger: `ordem-008-par` e `order-8`.

### A regressão que as asserções existentes pegaram

A terceira condição do Imediato — *"20 asserções existentes sem edição; se alguma precisar
mudar, pare e reporte"* — não foi cerimônia. **Nenhuma precisou mudar; o código é que
estava errado**, e foram elas que provaram.

Eu levantei a recusa de dentro do `transaction.atomic()`. Isso reverte o bloco — e o que o
bloco escreveu antes de recusar são os **alertas de glosa** que a avaliação acabara de
persistir. O `return Response(...)` original sai do `with` normalmente e **comita**. Trocar
`return` por `raise` parece equivalente e não é: o 409 passou a devolver ao cliente o id de
um alerta que não existia mais, e o `acknowledge` seguinte respondia **404**.

```
test_acknowledge_block_then_reclose_succeeds   FALHOU nas 4 classes de test_glosa_safety.py
AssertionError: 404 != 200
```

Conserto: a metade transacional (`_tentar_fechar`) **devolve** a recusa; `fechar_lote`
levanta depois do commit. Isto é o que motivou partir a função em duas — por
responsabilidade, não para caber no sensor de tamanho, que marcou a versão original com 95
linhas. A parte transacional segue inteira de propósito: a fronteira dela é o alcance do
lock de linha, e auxiliares que só são seguros numa ordem exata dentro da mesma transação
seriam design pior.

### Uma segunda lacuna de fixtura, da mesma família do CNES

Sem CBO o teste morria no XSD antes de chegar à asserção. `CBOS` é enumeração **fechada**
no XSD da ANS: string vazia não é campo em branco, é valor fora do conjunto, e o lote
inteiro reprova. Pus `225125` — taxonomia real, a mesma que `seed_revenue_staging` usa. Sem
isso o par teria falhado dos dois lados e provado nada, que é exatamente a armadilha em que
a ordem 007 já caiu uma vez.

### A prova em staging

Imagem `sha256:737358e2…` (revisão `4cf5b18`) na lab, digest anterior `bbe3d8da…` anotado,
pilha inteira `healthy`, smoke **10 passadas / 0 falhas / 0 puladas**. `latest` não se moveu
— segue em `3bb9a53`, a build de onda0, como a guarda da ordem 005(c) manda.

```
5. Faturamento
   status do lote: closed
   valor do lote : R$ 100.00
   fechado em    : 2026-09-13 04:31:51.262369+00:00
```

E lido do banco, não da saída do comando:

```
2026090005 | closed | 100.00 | 2026-09-13 04:31:51.262369+00
guia no lote: 202609000006 | 100.00
```

### O que ficou de pé, e o que não

De pé: a Prioridade 2 do INTENT passa a ter faturamento como **estado persistido**, não
como número impresso. Os lotes `2026090003`, `2026090004` e `2026090005` estão `closed` com
valor gravado; os da ordem 006 (`2026090001`, `2026090002`) ficam abertos e zerados de
propósito, como registro do estado anterior.

Não: a guia termina em `draft`, não em `submitted`. O fechamento só promove guia que está
em `pending` (`status="pending"` no filtro), e a cadeia cria em `draft`. É comportamento do
caminho original, não da extração, e está fora do escopo aprovado — fica registrado, não
corrigido por conta própria.
