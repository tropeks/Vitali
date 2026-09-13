<!-- maestro-order v1
id: 009
ts: 2026-09-13T01:48:37-03:00
epoch: 1789274917
head: f65fb1d834a790f2a3734c5ef220666e99723981
branch: order/009-ciclo-de-vida-da-guia
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 009 — Prioridade 2: a guia entra no ciclo de vida e lote fechado significa enviado

## Contexto

### Primeiro, a resposta à sua pergunta sobre a segunda cunha: nenhuma, hoje

Medido no banco da lab (schema `demo`), não suposto:

| cunha | dado que ela precisa | o que existe em staging |
|---|---|---|
| `no_show_prediction` | histórico de faltas | 4 agendamentos, **0 no-show**, 0 `NoShowRisk` |
| `deterioration_safety` | os 7 parâmetros do NEWS2 | 3 registros de sinais vitais, **só `heart_rate=76`**; 6 de 7 nulos |
| `allergy_safety` | alergias + prescrições | **0 alergias, 0 prescrições** |
| `dose_safety` | prescrições + regra de dose | **0 prescrições** — e a regra é do farmacêutico |
| `stockout_safety` | série de movimentação | **1 item, 1 movimento** — não há série |
| `controlled_safety` | dispensações | **0 dispensações** |

Nenhuma está travada por código faltando. Todas estão travadas por **dado ausente**. A
cunha de deterioração é a mais perto — o motor `news2` já existe, a regra é padrão
publicado do RCP (não número inventado), e `deterioration.py:117` já a torna inerte com
vitais incompletos, por desenho correto. Mas destravá-la exigiria **inventar observação
clínica**, que o INTENT §Limites proíbe. Então não proponho cunha: proponho o elo que
ainda está aberto na Prioridade 2 — e que, de quebra, destrava a terceira checagem da
cunha de glosa sem inventar número nenhum.

### O elo aberto: a guia nunca entra no ciclo de vida

`GUIDE_STATUS` é `draft → pending → submitted → paid/denied/appeal`
(`billing/models.py:23-30`). Medido:

- **Nada no código move `draft` para `pending`.** A única escrita de status no caminho de
  lote é `batch_lifecycle.py:180`, que promove `pending → submitted`. Guia criada como
  rascunho fica rascunho para sempre.
- Os quatro criadores nascem `draft` de propósito: `lab_order_billing.py:126`,
  `inpatient_billing.py:393`, `surgery_billing.py:96`, e a cadeia.
- **Consequência 1:** os seis lotes `closed` em staging contêm guias em `draft`. Lote
  fechado cheio de rascunho é estado incoerente — e é o "sinal verde que não significa
  verde" do §Limites.
- **Consequência 2:** `_ACTIVE_GUIDE_STATUSES = ["pending","submitted","paid"]`
  (`glosa_safety.py:85`) exclui `draft`, então a checagem `duplicate` da cunha é
  **inalcançável por construção** — a ordem 007 registrou isso como limite e a causa é esta.
- **Consequência 3:** `docs/PLAN_SPRINT10.md:83` calcula taxa de glosa sobre um
  denominador que exclui rascunhos. Clínica cujas guias nunca saem de `draft` mede glosa
  sobre denominador vazio.
- `docs/EPICS_AND_ROADMAP.md:450` já registra a caixa **desmarcada**: "Guide lifecycle
  (draft → pending → submitted → paid/denied)".

Há ainda uma contradição: `TISSGuideViewSet.submit` (`views.py:1300-1321`) aceita `draft`
e salta direto para `submitted`, pulando `pending` — apesar da docstring dizer
"pending → submitted". Uma guia pode virar "Enviada" sem nunca ter entrado em lote nem
sido validada contra o XSD.

Autoriza a ordem: INTENT v5 §Prioridades item 2 (receita antes de escopo novo) e §Limites
("sinal verde tem que significar verde"; compliance como gate).

## Abordagem — estrito, conforme sua decisão

1. **`services/batch_lifecycle.py`** ganha `marcar_pronta_para_envio(*, guia, actor)`:
   `draft → pending`, recusa qualquer outro estado de origem, e escreve `AuditLog`
   (`guide_marked_ready`) — declarar que uma guia pode ir à operadora é ato auditável,
   como o override de glosa da ordem 007.
2. **`fechar_lote` recusa lote com rascunho**: nova recusa `LoteComRascunho`, carregando a
   lista de guias em `draft` (número e id). A view traduz em **409** com o mesmo formato
   por guia que o bloqueio de glosa já usa — a tela de lote
   (`frontend/app/(dashboard)/billing/batches/[id]/page.tsx`) já sabe interpretar formas
   de 409, então a recusa entra no padrão existente.
3. **A cadeia declara a própria guia pronta**: `verify_revenue_chain` chama
   `marcar_pronta_para_envio` antes do fechamento. Ela pode declarar honestamente porque
   monta a guia completa de propósito e valida contra o XSD antes.
4. **Frontend**: a tela de lote passa a mostrar quais guias estão em rascunho quando o 409
   chega, com ação explícita "declarar prontas" (chamando o endpoint da transição) e novo
   fechamento. Um clique a mais, explícito e auditado — em vez de promoção silenciosa.
5. **Endpoint da transição**: `POST /api/v1/billing/guides/{id}/marcar-pronta/`, mesmo
   gate de permissão do resto de billing (`IsFaturistaOrAdmin`).

## O que eu NÃO faço, e por quê — sua condição (3)

**`from_lab_order`, `from_admission` e `bill_surgical_materials` não vão declarar pronto
automaticamente.** Eles criam guia a partir de pedido de exame, internação e caso
cirúrgico — e nascem `draft` por escolha deliberada dos três services. Marcá-las `pending`
na criação equivale a afirmar que uma guia gerada de uma internação está conferida e pode
ir à operadora **sem ninguém ter olhado**. Isso é declaração desonesta, e é exatamente o
caso que sua condição (3) manda parar e reportar.

Eles não fecham lote — devolvem a guia. Quem fecha é a tela de lote e a cadeia, e é lá que
a declaração de prontidão entra (passos 2–4). Nenhum fluxo existente quebra: o da tela
ganha um passo explícito; o da cadeia declara por conta própria.

**`TISSGuideViewSet.submit` fica como está nesta ordem.** Corrigir o salto
`draft → submitted` muda contrato HTTP de um endpoint que o frontend pode estar usando
para outro fim. Fica registrado como achado, para ordem própria.

## Teste que falha antes

- `test_fechar_lote_recusa_rascunho.py`: lote com guia `draft` → `fechar_lote` levanta
  `LoteComRascunho` nomeando a guia; o lote continua `open`. Hoje fecha.
- `test_marcar_pronta.py`: `draft → pending` grava `AuditLog`; estado de origem inválido é
  recusado.
- `test_verify_revenue_chain_closes_batch.py` (existente) ganha asserção: a guia termina
  **`submitted`**, não `draft`. Hoje falha — é a ressalva que registrei na ordem 008.
- **Um teste por chamador**, como você exigiu: cadeia, e os três criadores provando que
  continuam entregando `draft` (o comportamento que eu decidi não mudar fica travado por
  teste, não por intenção).
- Rede de proteção: as **143 asserções** de `test_billing.py` e `test_glosa_safety.py`
  passam sem edição. Se alguma exigir mudança, paro e reporto.

## Prova

1. Par antes/depois medido em container na lab, sha256 dos logs no ledger.
2. `ruff check`, `ruff format --check`, `lint-imports`, `mypy` antes do push.
3. CI verde nos cinco jobs no tip.
4. Em staging, por comando: a cadeia deixa a guia em **`submitted`** e o lote `closed` com
   R$ 100,00 — lido do banco. E uma tentativa de fechar lote com rascunho devolvendo 409
   com a guia nomeada. Recibo `order-9`.
5. **O bônus medido:** com guias em `submitted`, a checagem `duplicate` da cunha de glosa
   deixa de ser inalcançável. Rodo `verify_glosa_wedge` e reporto se ela dispara — sem
   inventar um único número.

## Risco

Muda o contrato do fechamento de lote: onde hoje devolve 200 com rascunhos, passará a
devolver 409. É mudança deliberada e é o ponto da ordem, mas atinge a tela de lote — por
isso o frontend entra no mesmo changeset, e não depois.

## Fora de escopo

Não corrige o salto `draft → submitted` do endpoint `submit` da guia; não toca nos seis
lotes já fechados em staging nem nas guias que eles contêm (ficam como registro do estado
anterior); não mexe em nenhuma cunha; não inventa dado clínico.


## Contrato de execução
- Trabalhe APENAS no branch `order/009-ciclo-de-vida-da-guia`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-9 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 009` (você não fecha a própria ordem).

## Aprovação

Aprovada pelo Imediato em 13/09, nas palavras dele:

> estrito, transição explícita e auditada, os três criadores continuam nascendo em
> rascunho (declarar pronto sem ninguém olhar seria desonesto — certo), 409 com a lista de
> rascunhos, frontend com ação explícita. O salto `draft→submitted` do endpoint `submit`
> vira issue agora, não fica só no plano. Prova = cadeia fechando lote com guia declarada
> pronta e lote com rascunho recusado, **ambos lidos do banco**.

O achado do endpoint `submit` virou a **issue #213**, aberta antes de qualquer código
desta ordem.

---

## Resultado

### O par, medido em container na lab

```
ANTES  (9002bef, os testes sozinhos)          6 failed, 55 passed
       cinco por a API não existir (ImportError: marcar_pronta_para_envio,
       LoteComRascunho) e um por asserção — 'draft' != 'submitted'
DEPOIS (eb21608)                            205 passed nas seis suítes afetadas
REDE   (as 143 asserções protegidas)        143 passed
FRONT                                         3 passed, incluindo o teste novo do
                                              409 de rascunho
```

`antes.log` sha256 `cd7d5065…86f49bb3c` · `final.log` `ea49ebf5…6a8c488e5a`.
Gate completo antes de cada push: `ruff check`, `ruff format --check`, `lint-imports`,
`mypy` (1055 arquivos), `tsc --noEmit`, `next lint`.

### A edição aditiva nas três asserções de fechamento

Condição do Imediato: só acrescentar. Resultado de `git diff --numstat`:
**17 adicionadas, 0 removidas.** Cada um dos três testes ganhou um
`POST /guides/{id}/marcar-pronta/` antes do `close` que já afirmavam; nenhuma asserção
enfraqueceu ou sumiu.

### O que a cunha ganhou de graça

`duplicate` (ANS 1702) **disparou** sobre dado real. A ordem 007 a registrou como
inalcançável por construção: `_ACTIVE_GUIDE_STATUSES` exclui `draft` e toda guia de
staging era rascunho. Com a cadeia deixando guia em `submitted`, a checagem passou a ter
o que ver — a terceira das três, sem inventar número clínico nem contratual.

### Duas quebras que eu causei, e o que cada uma ensinou

**1. O harness da ordem 007.** O fechamento estrito barra rascunho ANTES de julgar glosa,
e o `--prove-block` montava guia em rascunho esperando o 409 de glosa. Consertado para
percorrer os dois portões em ordem: exercitar um gate com dado que o gate anterior recusa
não prova nada sobre o segundo.

**2. O recibo que mentiu.** Gravei um `order-9` com `exit 0` sobre uma execução que tinha
quebrado com traceback. Causa: o comando do recibo canalizava o `docker exec` para um
`sed`, e o status do pipeline veio do `sed`. É o mesmo defeito que esta série vem achando
em toda parte — caminho de erro que reporta sucesso — desta vez dentro do meu próprio
comando de prova, que é o pior lugar onde ele pode estar. A quebra por baixo era legítima:
o harness escolhia o alerta da guia mais ANTIGA, e as antigas já estão em lote fechado,
então a guarda de dupla apresentação disparava corretamente sobre um cenário que eu montei
errado. Corrigido em `c9049d1`.

**Regra que sai daqui, dada pelo Imediato:** o recibo é a ÚLTIMA ação no tip. Depois dele
nada muda na árvore — nem documento, nem brief. Gravar e então commitar vence o recibo, e
foi o que fiz duas vezes.

### O que ficou de fora, de propósito

Os três geradores (`from_lab_order`, `from_admission`, `bill_surgical_materials`) seguem
entregando `draft`, travados por `test_guide_creators_stay_draft.py`. Declarar pronto na
criação afirmaria à operadora que uma guia derivada de evento clínico está conferida sem
ninguém ter olhado.

O salto `draft → submitted` do endpoint `submit` da guia virou a **issue #213**, aberta
antes de qualquer código desta ordem.
