<!-- maestro-order v1
id: 006
ts: 2026-09-12T11:33:18-03:00
epoch: 1789223598
head: 2552edf17d08a9897da982868d092ab35183823d
branch: order/006-receita-fim-a-fim
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 006 — Prioridade 2: percorrer guia TISS válida → lote → faturamento fim a fim em staging, e consertar o que bloqueia




**Direção:** INTENT v5 — §Prioridades **item 2**, *"Receita destravada antes de escopo novo.
O caminho guia TISS válida → lote → faturamento tem precedência sobre qualquer módulo
adicional."*

---

## 0. A resposta curta

**Não falta código. Falta a cadeia nunca ter sido percorrida onde importa** — e é a terceira
vez nesta sequência que o padrão se repete: os catálogos existiam e nunca eram carregados
(002), o backup existia e nunca rodava (003), e agora a receita está implementada, coberta
por teste, e **nunca produziu uma guia em staging**.

Medido no banco da lab, schema `demo`:

| Tabela | Linhas | |
|---|---:|---|
| `emr_patient` | 4 | há dado clínico |
| `emr_encounter` | 4 | |
| `emr_admission` | 3 | |
| `emr_encounterprocedure` | 1 | |
| **`billing_insuranceprovider`** | **0** | ← **o bloqueio duro** |
| `billing_pricetable` / `pricetableitem` | 0 / 0 | |
| **`billing_tissguide`** | **0** | nenhuma guia, nunca |
| **`billing_tissbatch`** | **0** | nenhum lote, nunca |

---

## 1. Notícia boa para o Capitão: a CBHPM **não** bloqueia a cadeia

Eu havia registrado a compra da tabela CBHPM como o item que trava a Prioridade 2. **Medido,
não é.**

```python
honorario_cbhpm = models.ForeignKey("core.CBHPMItem", on_delete=models.PROTECT,
                                    null=True, blank=True, ...)
price_table     = models.ForeignKey(PriceTable, on_delete=models.SET_NULL,
                                    null=True, blank=True, ...)
```

Os dois são **opcionais**. A CBHPM **valora o honorário** (porte × valor-CH); não é
pré-requisito de existir guia, de validar XML nem de fechar lote. A guia sai, valida contra
o XSD e entra no lote sem ela — com o honorário em zero.

**O que isso muda para a decisão dele:** comprar a CBHPM deixa de ser "destravar a receita" e
passa a ser "valorar corretamente o honorário médico". Continua importante e continua dele —
mas não é o que impede de provar a cadeia, e ele não precisa decidir antes desta ordem.

---

## 2. O bloqueio duro, e ele é de cadastro

```python
provider = models.ForeignKey(InsuranceProvider, on_delete=models.PROTECT, related_name="guides")
```

Sem `null=True`. **Zero operadoras em staging ⇒ nenhuma guia pode existir.** É o primeiro
elo, e ele é dado de cadastro, não funcionalidade.

Existe `manage.py import_insurances --file <csv> --tenant <schema>`, com `--dry-run`. Não
falta ferramenta; falta a linha no banco.

A `PriceTable` é opcional, mas sem ela **todo item vale zero** — e "faturamento" de R$0,00
não prova cadeia nenhuma. Entra como necessária de fato, ainda que não por FK.

---

## 3. O achado: há código morto e quebrado escondido atrás de um `return` silencioso

`seed_demo_data._create_guides` (`:225-250`) é a função que deveria popular guias no demo:

```python
provider = InsuranceProvider.objects.first()
tuss_codes = list(TUSSCode.objects.filter(active=True)[:10])
if not provider or not tuss_codes or not encounters:
    return                      # ← sem log, sem aviso
```

É **por isso** que o staging tem paciente, atendimento e internação, mas zero guias: o seed
procurou operadora, não achou, e desistiu em silêncio. E o próprio seed **não cria
operadora nenhuma** — a demo é estruturalmente incapaz de produzir uma guia.

**Pior:** o corpo que o `return` protege está quebrado. Ele chama

```python
TISSGuide.objects.create(patient=..., professional=..., encounter=...,
                         insurance_provider=provider, ...)
```

e os campos reais do modelo são **`provider`** e **`executor`** — `insurance_provider` e
`professional` **não existem**. No instante em que alguém fizer a coisa óbvia — cadastrar
uma operadora — o `seed_demo_data` passa a estourar `TypeError`.

O guard silencioso vem escondendo isso. É o mesmo desenho que a ordem 003 encontrou no
`restore_test.sh`: um caminho de erro que engole a própria falha e faz o defeito esperar
pelo primeiro usuário.

---

## 4. O que já está provado, e não precisa ser refeito

A lógica da cadeia **tem cobertura**: `validate_xml` é chamado **21 vezes** em
`test_xml_engine.py`, e `TISSBatch` aparece em três arquivos de teste
(`test_xml_engine.py`, `test_billing.py`, `test_glosa_safety.py`). A suíte passa no CI.

Então esta ordem **não reescreve motor de XML nem lógica de lote**. Ela leva dado real à
cadeia que o teste já exercita com dado sintético, e conserta o que só aparece fora do teste.

---

## 5. Plano

**Passo 1 — Cadastro mínimo e realista, por comando, não por SQL.** Uma `InsuranceProvider`
e uma `PriceTable` com itens ligados a códigos TUSS **que existem no catálogo carregado**
(54.139 disponíveis). Via `import_insurances` e o caminho de preço equivalente; nada de
`INSERT` à mão, porque o objetivo é que o procedimento seja repetível em ambiente novo — a
lição da 002.

> **Decisão do Imediato:** dado de operadora **fictício mas realista** (nome inventado,
> registro ANS com forma válida) ou **uma operadora real**? Recomendo fictício: staging não
> tem contrato com ninguém, e registro ANS real num ambiente de teste convida a confusão.
> O INTENT §Limites proíbe inventar número de ANS **em código** — um CSV de cadastro de
> staging, marcado como fictício, não é isso; mas a fronteira é do Imediato.

**Passo 2 — Consertar o `_create_guides`.** Nomes de campo corretos, e o `return` silencioso
vira aviso explícito dizendo **o que falta** ("sem InsuranceProvider — rode
`import_insurances` antes"). Teste de regressão que o execute com operadora presente, para
que o corpo pare de ser código que ninguém roda.

**Passo 3 — Percorrer a cadeia, de ponta a ponta, com o que existe.** Uma guia de consulta a
partir de um `emr_encounter` real → itens com TUSS do catálogo → `validate_xml` contra o XSD
→ lote → envelope. Cada etapa registra o que produziu.

**Passo 4 — Medir o que a cadeia NÃO alcança.** Segundo o `VITALI_HANDOFF_MIGRACAO.md`, a
guia de internação parava em `dadosInternacao`/`tipoFaturamento` e a SP/SADT em
`dadosSolicitante`. **Os campos `tipo_faturamento` e `requesting_professional` existem hoje
no `TISSGuide`** — a Onda 4 os criou. Então a pergunta mudou de *"falta modelo"* para *"o
fluxo preenche?"*. O passo mede, não supõe.

**Passo 5 — Registrar o procedimento.** Onde couber no `docs/`, como o
`scripts/catalogs/README.md` faz para catálogo: o que um ambiente novo executa para ter uma
cadeia de receita viva.

---

## 6. O que esta ordem NÃO faz

- **Não compra nem carrega CBHPM** (§1): não é bloqueio, e a decisão é do Capitão.
- **Não reescreve o motor de XML nem o de lote** (§4): têm teste e passam.
- **Não envia nada para operadora nenhuma.** Lote gerado e validado, não transmitido.
- **Não inventa número clínico ou de ANS em código** — INTENT §Limites.
- **Não leva nada para `master`.**

## 7. Risco

| Risco | Mitigação |
|---|---|
| Escrever dado de cadastro no staging recém-migrado | Dado de cadastro, não clínico, em tenant `demo`; o `import_insurances` tem `--dry-run`, e o drill da 003 prova que dá para voltar |
| Dado fictício virar dado "real" por esquecimento | Prefixo e marcação explícita, como o `seed_demo_data` já faz com `DEMO-`/`DEMO_` para catálogo governado |
| A cadeia parar num gap de produto (`tipo_faturamento`) | É resultado, não fracasso: o passo 4 existe para medir onde para e com qual mensagem |

## 8. Prova

- `billing_insuranceprovider ≥ 1`, `billing_pricetableitem ≥ 1` com TUSS do catálogo real.
- **Uma guia que passa no `validate_xml` contra o XSD**, com o retorno registrado.
- **Um lote** contendo essa guia, com envelope gerado.
- `seed_demo_data` executando o corpo de `_create_guides` sem `TypeError`, com teste que
  falha se os nomes de campo divergirem de novo.
- O ponto exato onde internação e SP/SADT param, medido e citado — ou a constatação de que
  não param mais.
- `maestro evidence --record --label order-6 -- <comando>` no tip.

---

## Contrato de execução
- Trabalhe APENAS no branch `order/006-receita-fim-a-fim`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-6 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 006` (você não fecha a própria ordem).
