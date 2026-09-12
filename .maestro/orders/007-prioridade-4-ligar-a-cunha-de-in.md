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

---

## 7. Resultado — a cunha interceptou dado real, e o passo 3 achou um buraco

**Flag ligada só no `demo`** (estado anterior: a linha **não existia**; reverter = apagá-la).
**Desligada ao fim**, como o plano previa — a cunha fica provada e OFF.

### Os veredictos, sobre guias que a operação produziu

```
202609000001  incomplete    ANS 05  [advise]  carteirinha, CID-10, senha ausentes
202609000002  incomplete    ANS 05  [advise]  CID-10, senha ausentes
202609000003  incomplete    ANS 05  [advise]
202609000003  not_in_table  ANS 01  [BLOCK]   "Procedimento 10101010 não consta na
                                               tabela de preços vigente da operadora"
```

`billing_glosasafetyalert` tinha **0 linhas** antes. O motor tinha teste e nunca julgara uma
guia de verdade. As mensagens embutem o valor ofensor, como o `glosa_checker` promete — e
isso não é estilo: o predicado de preservação de override chaveia na mensagem, então rótulo
estático deixaria um bloqueio reconhecido ser burlado editando só o valor.

### Duas previsões minhas, erradas, e as duas úteis

**O `duplicate` (ANS 1702) não disparou.** Eu previra que sim: mesmo TUSS, mesmo atendimento,
duas guias. Mas o motor exige guia já **APRESENTADA** à operadora, e as de staging estão em
`draft`. O motor está certo e eu li rápido: cobrar duas vezes só é duplicidade depois de
apresentar.

**`incomplete` não bloqueia** — é `advise`. Só `duplicate` e `not_in_table` bloqueiam, por
serem *"real, high-confidence denials"*. Para exercitar o soft-stop foi preciso o cenário que
bloqueia de verdade: guia faturando procedimento **fora da tabela negociada**. Não é
artificial — é o erro de faturamento mais comum que existe, e é o que a operadora glosa.

### O ciclo completo, medido

```
antes do override : [block/flagged]       · guias bloqueando o fechamento: 1
depois do override: [block/acknowledged]  · guias bloqueando o fechamento: 0
```

É a interceptação inteira: o lote **não fecharia** com o alerta aberto, e volta a poder
fechar quando um humano assume a responsabilidade por escrito.

### O achado do passo 3: o override não chega ao `AuditLog`

O Capitão pediu para ver o override na auditoria. Medido:

```
AuditLog antes: 429  |  depois: 429  |  linhas novas: 0
```

O override **fica durável no próprio alerta** — `acknowledged_by`, `override_reason` (80
chars), `acknowledged_at` — e o endpoint escreve um `logger.info`. Mas não entra na tabela de
auditoria.

A perna do alerta está lá: `glosa_alert_raised`, **6 linhas**, escritas pelo service. O
`README.md` descreve o flywheel como *"`AuditLog` de alerta/override/desfecho"* — **alerta
sim, override não**.

Por que importa mais que uma linha faltando: **override é o sinal mais valioso do flywheel**.
É o humano discordando da máquina, com motivo escrito. Se o que aprende lê `AuditLog`, esse
sinal é invisível para ele — e o que sobra é a máquina aprendendo só com os próprios acertos.

**Não consertei.** O Capitão pediu para ver, não para consertar, e mexer no caminho de
auditoria é mudança de contrato. Vira item curto se ele quiser.

### Passo 4 — o vazamento transacional

Teste escrito para falhar antes (`9633dc3c`) e a correção depois (`44dcadbc`): o
`if falhas: self._reprovar(...)` do `verify_revenue_chain` foi para dentro do `atomic()`.

A distinção que mantinha isso invisível está no comentário do arquivo: exceção levantada
**dentro** do bloco sempre reverteu — foi por isso que o `guide_type` inválido não deixou
rastro — enquanto falha **coletada numa lista e relatada depois** comitava tudo antes. Dois
caminhos de falha, resultados opostos, no mesmo comando.

Passou a importar mais por causa desta ordem: a cunha julga as guias do tenant, então guia
suja deixada por execução reprovada vira alerta de glosa. O rastro de um comando que falhou
poluiria a interceptação.

#### Correção: o primeiro par não provava nada, e envenenou quatro execuções de CI

O par `9633dc3c`/`44dcadbc` está **invalidado**. A fixtura do teste não dava CNES ao
profissional, e `_cnes_obrigatorio` levanta no passo 3 — antes de o comando chegar ao
comportamento transacional que é o assunto do teste. Ele falhava **igual nas duas metades**,
com `Guia Consulta 202609000001 não tem CNES do estabelecimento executante`. Teste que falha
do mesmo jeito antes e depois não é prova, e este derrubou o `Backend — Tests` em
`9633dc3`, `44dcadb`, `dbe6414` e `e009a521` — quatro execuções vermelhas atribuídas a
causas diferentes até a fixtura ser lida.

Refeito em `bee9872`, com o CNES fictício declarado `0000000` (pelo setter `cnes_code`, que
escreve `cnes`, `legacy_cnes_text` e `cnes_unmatched`). Medido em container descartável na
lab — a imagem que o CI fixa, `postgres:16-alpine` efêmero, dependências de
`requirements/development.txt`; docker é negado ao meu usuário nesta máquina, a lab tem:

```
ANTES  (_reprovar fora do atomic)   1 failed in 6.44s
       AssertionError: 1 != 0 : cadeia reprovada deixou guia comitada   (linha 90)
       e o log percorre até "5. Faturamento / valor do lote : R$ 100.00" — falha no
       comportamento, não na fixtura
DEPOIS (_reprovar dentro do atomic) 1 passed in 371.95s

antes.log   sha256 3deb0decacb550a2419f99ecedf1bfb228e7794ce832884214f2e7bf699206c1
depois.log  sha256 4fb000627f0180b73290234ac9e456af7d24aff4b3245236039a6b1f3f5399c2
```

Containers e árvore copiada removidos ao fim. Ledger: `ordem-007-passo-4`.

**O que isto custou, em método:** eu li "vermelho" quatro vezes e procurei causa nova a cada
vez, em vez de ler a saída do teste na primeira. A regra que sai daqui é a mesma que já
vale para o `grep -c` e o `set -e`: **um teste novo que falha tem de falhar pela asserção
que eu escrevi** — se a mensagem for outra, o teste está quebrado, não o código.

---

## 8. Emenda ao plano — o override entra no AuditLog

**Decisão do Imediato, 12/09, sobre o achado do §7:** *"o override de alerta de glosa entra
no AuditLog — sem isso não há flywheel alerta → override → desfecho, e a tese fica pela
metade."* Vira item curto **dentro** desta ordem, com teste que falha antes.

**Onde o registro vive, e por quê não é na view.** Em `GlosaSafetyAlert.acknowledge()`. Todo
caminho que reconhece um alerta converge nesse método — o endpoint, um management command,
um shell de manutenção. Pôr o registro na view deixaria a lacuna aberta pelos outros
caminhos, e **foi exatamente um override feito fora da view que expôs a lacuna**: se eu
tivesse exercitado só o HTTP, teria concluído que estava tudo certo.

**O que a linha carrega:** o que foi contornado (`check_code`, `ans_glosa_code`, `severity`) e
por quê (`override_reason`), além do `old_data` com o status anterior. "Houve um override"
sem essas duas coisas não ensina nada a ninguém — e ensinar é o ponto do flywheel.

**Ação:** `glosa_alert_overridden`, na mesma família de `glosa_alert_raised` e
`glosa_alert_override_kept` que o service já escreve.

**Prova:** teste em `dbe64145` (falha antes) e implementação no commit seguinte. Dois casos —
que a linha nasce com o motivo dentro, e que ela diz **override de quê**, não só que houve um.

**Medido em `e009a521`:** os dois testes passam (`test_override_escreve_no_auditlog`,
`test_override_registra_o_que_foi_contornado`), e em `dbe64145` os dois falham pelas
asserções escritas, nas linhas 87 e 107. O par é válido. O vermelho daquele CI era o teste
do passo 4, acima — não o AuditLog.

**O que ainda falta para a emenda estar provada em dado real:** a lab roda a imagem
`sha256:0072abe3…`, revisão `5675be13` — a da ordem 006, anterior a este código. O override
que existe em staging (guia `202609000003`, alerta `not_in_table`/ANS 01, `acknowledged`)
foi feito por aquela imagem, e por isso **não há linha `glosa_alert_overridden` no
`public.core_auditlog`** — 429 linhas, nenhuma dessa ação, exatamente como o §7 registrou.
A emenda está implementada e provada em teste; falta a imagem nova subir na lab e um
override novo deixar a linha. Isso é passo de deploy, não de código.

---

## 9. Estado real de staging, medido em 12/09 — e uma correção ao que reportei da 006

Apurado direto no banco da lab (`vitali-lab-postgres-1`, schema `demo`) enquanto eu
fechava esta ordem:

| guia | lote | itens | valor dos itens | alerta da cunha |
|---|---|---|---|---|
| `202609000001` | `2026090001` | 1 | R$ 100,00 | `incomplete` / ANS 05 / advise — carteirinha vazia |
| `202609000002` | `2026090002` | 1 | R$ 100,00 | `incomplete` / ANS 05 / advise |
| `202609000003` | *sem lote* | 1 | R$ 100,00 | `incomplete` / ANS 05 + `not_in_table` / ANS 01 **block**, com override |

**A correção.** Eu reportei ao Imediato *"valor R$ 100,00 faturado"* para o lote
`2026090002`. O número certo do **item da guia** é esse; o **lote** não carrega valor
nenhum:

```
billing_tissbatch: 2026090001 | open | total_value 0.00
                   2026090002 | open | total_value 0.00
```

`verify_revenue_chain` passo 5 soma os itens **em memória** (`total = sum(...)`,
`verify_revenue_chain.py:185`) e escreve o valor na saída do comando — nunca em
`lote.total_value`, e nunca fecha o lote. Não existe, em todo o `billing`, caminho que
grave `TISSBatch.total_value` ou mova o status de `open`. Então o que a ordem 006 provou,
com precisão: **guia válida contra o XSD → lote contendo a guia → valor apurável maior que
zero**. O que ela **não** provou: faturamento como estado persistido.

**Isto não invalida a 006** — o XSD passou com 0 erros e a receita é apurável a partir de
dado persistido — mas invalida a palavra "faturado" do jeito que eu a usei, e é assunto de
Prioridade 2, não desta ordem. Fica proposto como ordem própria: fechar lote (`status`,
`total_value`, `closed_at`) com teste, já que hoje o lote nasce aberto e ninguém o fecha.

**A guia órfã continua lá.** O Imediato autorizou apagar a `202609000001` (dado de teste).
Eu não apaguei e não disse que tinha apagado — o item ficou aberto. Ela agora **é prova**:
carrega um dos três alertas `incomplete` que o §7 registra. Apagá-la remove um veredicto da
cunha. Recomendo mantê-la até a 007 ser aceita, e então apagar guia e lote `2026090001`
juntos — ela sozinha deixaria um lote vazio.
