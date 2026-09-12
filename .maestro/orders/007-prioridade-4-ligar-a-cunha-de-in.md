<!-- maestro-order v1
id: 007
ts: 2026-09-12T18:22:15-03:00
epoch: 1789248135
head: f3125f5ac4f96525dd88a6dd8de4656d9fe2657b
branch: order/007-cunha-glosa
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 007 — Prioridade 4: ligar a cunha de interceptacao de glosa sobre dado real de staging




**Direção:** INTENT v5 — §Prioridades **item 4**, *"Interceptação sobre registro. Entre
melhorar um CRUD e fechar uma cunha de interceptação (dose, glosa, ruptura), a cunha ganha —
é a tese do produto."*

---

## 0. Qual cunha, e por que não é escolha de gosto

São sete cunhas construídas com flag OFF. A pergunta que decide não é qual é mais
interessante — é **qual tem, em staging, o dado real de que precisa para interceptar de
verdade**. Medido no `demo`:

| Cunha | O que precisa | Staging tem | Veredito |
|---|---|---|---|
| **dose-safety** | `DoseRule` **validada por farmacêutico** + prescrições para checar | 2 regras, **0 validadas**; **0 prescrições** | **bloqueada duas vezes**: pela decisão D-T1 (humana) e por não haver o que interceptar |
| **stockout** | histórico de movimentação para prever ruptura | **1** `StockMovement` | **sem base**: não se prevê série temporal com um ponto |
| **glosa** | guias TISS e tabela de preço ativa | **2 guias, 2 lotes, tabela ativa** — criados pela ordem 006 | **pronta** |

A resposta veio da ordem anterior: **a 006 produziu as primeiras guias TISS que este sistema
já teve fora de teste**, e é exatamente esse o insumo da cunha de glosa. A Prioridade 2
destravou a Prioridade 4 — na ordem que o INTENT prevê.

---

## 1. Dois gates que costumam travar cunha de IA, e aqui não travam

**Não precisa de LLM.** O motor é declaradamente determinístico
(`billing/services/glosa_checker.py`): *"NO LLM, NO network, NO clock … The engine DECIDES
(authoritative, like the dose engine); a future LLM only explains/prioritises."* O
orquestrador pré-computa tudo que vem do banco e passa um `GuideContext` puro.

**O DPA está assinado.** `core_aidpastatus` para o tenant `demo`: **21/07/2026**. O
INTENT §Limites exige DPA assinado antes de processar dado de saúde, e ele existe — ainda
que, sendo motor determinístico sem LLM, esta cunha não dependa disso.

Ou seja: a cunha de glosa é a única das três que não espera decisão humana nem dado que não
existe.

---

## 2. O dado de staging dispara duas das três checagens — e não foi encomendado

O motor tem três veredictos, com código ANS (`GLOSA_REASON_CODES`):

| Veredicto | Código ANS | Significado |
|---|---|---|
| `not_in_table` | **01** | procedimento não coberto |
| `incomplete` | **05** | inconsistência nos dados do beneficiário (carteira, competência, CID-10) |
| `duplicate` | **1702** | procedimento já apresentado em outra guia do mesmo atendimento |

As duas guias que a 006 deixou em staging:

```
guia         carteira            competência  CID-10  atendimento
202609000001 (vazia)             2026-09      []      9eac8c78…
202609000002 FICTICIA-STAGING    2026-09      []      9eac8c78…
itens: as DUAS com TUSS 10101012
```

Então, sem preparar nada:

- **`incomplete` (ANS 05)** nas duas — nenhuma tem CID-10, e a primeira nem carteira;
- **`duplicate` (ANS 1702)** — mesmo TUSS, no **mesmo atendimento**, em duas guias;
- **`not_in_table`** não dispara: 10101012 está na tabela de preço ativa.

Nenhuma dessas guias foi construída para a cunha. Saíram de percorrer a cadeia duas vezes.
**É o melhor tipo de dado de teste: o que a operação produziu sozinha.**

> **Achado colateral, e é defeito meu.** A guia `202609000001` não deveria existir: ela é
> resto da execução que reprovou no XSD. O `if falhas: self._reprovar(...)` final do
> `verify_revenue_chain` está **fora** do `with transaction.atomic()`, então a guia e o lote
> comitam e só depois o comando reporta falha. Eu havia afirmado ao Imediato que o `atomic()`
> limpava o rastro — vale para a exceção levantada *dentro* do bloco (foi o caso do
> `guide_type` inválido), e não para a falha coletada e reportada no fim. Conserto entra
> nesta ordem, no passo 4.

---

## 3. Plano

**Passo 1 — Ligar a flag no tenant `demo`, e só nele.** `glosa_safety` por tenant, como o
INTENT §Limites exige ("qualquer feature nasce ligável e desligável por cliente"). Estado
anterior anotado para desligar em um comando.

**Passo 2 — Rodar a cunha sobre as guias reais e registrar o que ela disse.** Cada
`GlosaSafetyAlert` com seu código ANS, a frase determinística em pt-BR e a guia que a
motivou. Hoje `billing_glosasafetyalert` tem **0 linhas**: o motor existe, tem teste, e nunca
julgou uma guia de verdade.

**Passo 3 — Provar o soft-stop, não só o alerta.** A tese da cunha não é "avisa": é
**intercepta antes do lote fechar**, com override auditado. O passo mede as duas metades —
que o fechamento do lote é bloqueado com alerta aberto, e que o override fica no `AuditLog`
(o flywheel `alerta → override → desfecho` do README).

**Passo 4 — Consertar o vazamento transacional do `verify_revenue_chain`** (§2): mover o
`_reprovar` final para dentro do `atomic()`, com teste que falha antes. Uma cadeia que
reprova não pode deixar guia comitada — ainda mais agora que a guia suja vira alerta de
glosa.

**Passo 5 — Desligar a flag ao fim, salvo decisão em contrário.** A cunha fica **provada e
OFF**, que é o estado que o INTENT pede: "flag de IA nasce OFF". Ligar para valer é decisão
de produto, não de ordem técnica.

---

## 4. O que esta ordem NÃO faz

- **Não liga as outras seis cunhas.** Dose e ruptura estão medidas como bloqueadas (§0).
- **Não cria dado para a cunha achar.** O valor da medição está em ela julgar o que a
  operação produziu. Se um veredicto não disparar, isso é resultado.
- **Não usa LLM.** O motor é determinístico e a ordem não acrescenta camada de explicação.
- **Não deixa a flag ligada** sem decisão explícita (§5).
- **Não leva nada para `master`.**

## 5. Risco

| Risco | Mitigação |
|---|---|
| Flag ligada em tenant errado | `demo` apenas, estado anterior anotado, passo 5 desliga |
| Soft-stop travar faturamento de staging | É staging, e o override existe por desenho — o passo 3 exercita justamente isso |
| A cunha não disparar nada | Resultado, não fracasso: significa que o `GuideContext` não chega como eu li, e aí a medição é o entregável |

## 6. Prova

- `glosa_safety` ON no `demo`, e OFF de novo ao fim (ou decisão registrada).
- **≥1 `GlosaSafetyAlert` sobre guia real**, com código ANS e a frase que o motor gerou.
- O `duplicate` (1702) disparando nas duas guias do mesmo atendimento — é o veredicto mais
  específico e o que menos depende de eu ter lido o motor certo.
- Soft-stop observado: lote bloqueado com alerta aberto, e `AuditLog` do override.
- `verify_revenue_chain` reprovando **sem deixar guia comitada**, com teste.
- `maestro evidence --record --label order-7 -- <comando>` no tip.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/007-cunha-glosa`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-7 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 007` (você não fecha a própria ordem).
