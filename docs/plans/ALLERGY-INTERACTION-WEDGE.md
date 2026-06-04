# Allergy & Drug-Interaction Wedge — Plano (5º wedge AI-native)

> **Tese:** completa a **trilogia de segurança medicamentosa** ([[VISION-AI-NATIVE]]).
> Dose respondeu *"é a quantidade certa?"*; este responde *"esse medicamento é seguro
> para ESTE paciente?"* — cruza cada item prescrito contra (a) as **alergias** registradas
> do paciente e (b) as demais drogas da prescrição (**interações**), no sign/dispense.
> Mesmo padrão **Observe→Predict→Intercept→Learn** dos 4 wedges.

## O que já existe (não reinventar)
- **`emr.Allergy`**: `substance` (CharField 200, **texto livre**), `reaction`, `severity`
  (mild/moderate/severe/life_threatening), `status` (active/inactive/resolved), FK paciente.
- **`pharmacy.Drug`**: `name`, `generic_name` (texto livre, ~INN), `anvisa_code`,
  `controlled_class`. **Sem ingrediente estruturado, sem ATC, sem tabela de interação.**
- **`emr.AISafetyAlert`** já tem `alert_type` **`allergy`** e **`drug_interaction`** +
  `source` (`llm`|`engine`). Hoje só o **LLM** (`check_prescription_safety`, Celery)
  escreve esses alertas — **não há motor determinístico**.
- **Gate de sign/dispense** já existe (`DoseCheckService.has_blocking_dose_alert`):
  bloqueia (409 soft-stop) se houver `AISafetyAlert(alert_type=dose, source=engine,
  severity=contraindication, status=flagged)`; override via `AcknowledgeSafetyAlertView`;
  frontend `DoseSafetyModal`. **Este wedge GENERALIZA o gate** para também bloquear
  alertas de alergia do motor — reaproveitando toda a superfície.

→ O wedge adiciona o **motor determinístico autoritativo** por trás de `allergy` /
`drug_interaction` (mirror do que dose fez), com o LLM existente rebaixado a explicador.

## ⚠️ O problema central (pro eng-review travar): casamento texto-livre
Alergia (`substance`, livre) × Droga (`generic_name`/`name`, livre). Um motor de
SEGURANÇA não pode errar:
- **Falso-negativo** (não casar uma alergia real) = perigo clínico → o motor deve ser
  conservador no que considera "sem conflito", e o LLM cobre o fuzzy como **advise**.
- **Falso-positivo** (casar errado por substring) = fadiga de alerta → bloqueio só em
  match de **alta confiança**.
- **Decisão do eng-review:** v1 casa por **normalização** (casefold + remove acento +
  token) de `Allergy.substance` vs `Drug.generic_name` (e `name`), match de token/palavra
  inteira (não substring solto). Adicionar campo estruturado de ingrediente no `Drug`
  (ex. `inn_name`/`active_ingredients`) **agora** ou depois? E **reatividade cruzada**
  (penicilina→cefalosporina, sulfas) exige **tabela curada** (verdade humana, inerte até
  preencher) — não dá pra inferir de texto.

## Arquitetura — espelha dose (padrão provado)
| Camada | Alergia/Interação |
|---|---|
| motor puro | **`AllergyChecker`** (`apps/pharmacy/services/allergy_checker.py`): dado a droga prescrita (name/generic), as alergias ATIVAS do paciente, a tabela de reatividade-cruzada (opcional), e as demais drogas da prescrição + tabela de interação (opcional) → `AllergyVerdict` (ALLERGY_CONFLICT / CROSS_REACTIVITY / INTERACTION / SAFE / NOT_APPLICABLE). PURO, sem DB. |
| orquestrador | estende/espelha `DoseCheckService` → escreve `AISafetyAlert(alert_type=allergy\|drug_interaction, source=engine)` |
| flag | **`allergy_safety`** (default OFF) — separada de `dose_safety` (depende de dados distintos) |
| gate | **generaliza** o soft-stop de sign/dispense para incluir contraindicação de alergia do motor |
| superfície | reaproveita `DoseSafetyModal` + `AcknowledgeSafetyAlertView` (talvez rótulo por `alert_type`) |
| flywheel | `AuditLog` por veredito (droga, alérgeno casado, severidade, regra) |

## Posture — block vs advise
- **Alergia confirmada severa/risco-de-vida + match direto de alta confiança → BLOCK**
  (soft-stop 409 + override-com-motivo, igual contraindicação de dose). É o núcleo do valor.
- **Reatividade cruzada / alergia mild-moderate / match de baixa confiança → ADVISE.**
- **Interação medicamentosa → ADVISE** por padrão (só combinação contraindicada da tabela
  curada → block). Determinístico autoritativo; LLM só explica/prioriza.
- **Nunca** inventa: reatividade-cruzada e interação vêm de **tabela curada humana**
  (inerte até preencher, como dose D-T1 / dados de contrato da glosa). Match direto de
  alergia roda sobre o dado existente, sem tabela nova.

## Sequência de PRs (a confirmar no eng-review)
- **A1 — motor + match direto + gate + flag:** `AllergyChecker` puro (normalização +
  match de token alergia↔generic_name; severidade→block/advise) + orquestrador
  (`AISafetyAlert` source=engine) + **generalização do gate** sign/dispense + flag
  `allergy_safety` OFF + testes. **Roda sobre dado existente** (sem tabela nova).
- **A2 — reatividade cruzada:** modelo `AllergenCrossReactivity` (classe→ingredientes,
  curado, inerte até preencher) + check `CROSS_REACTIVITY` (advise) + testes.
- **A3 — interação medicamentosa:** modelo `DrugInteraction` (A×B→severidade, curado) +
  check `INTERACTION` no orquestrador (par-a-par na prescrição, single-query) + testes.
- **A4 — superfície:** rótulos por `alert_type` no `DoseSafetyModal`/ack (ou painel),
  frontend mínimo. Sem block novo.

## ✅ LOCKED (eng-review Gemini, 54s)
- **Schema em A1:** adicionar `Drug.active_ingredients` (lista estruturada, JSONField
  default=[]). Sistema de segurança não pode depender só de texto sujo; curar esse campo
  vira pré-requisito de confiança do motor. Inerte (vazio) → cai no fallback texto-livre.
- **Algoritmo de match (LOCKED):** **Normalized Token Subset**. (1) normaliza: casefold +
  remove acento + tira pontuação; (2) tokeniza por `\b\w+\b`; (3) casa se
  `set(tokens(allergy.substance)).issubset(tokens(name) ∪ tokens(generic_name) ∪
  tokens(active_ingredients))`. **NUNCA substring crua** (mata o falso-positivo
  "AAS"∈"AASystem"). issubset é conservador contra falso-positivo; o LLM existente cobre
  o recall (falso-negativo) como **advise**.
- **Posture (CORREÇÃO do plano):** **QUALQUER** match direto de alergia **ativa** pelo
  motor → **BLOCK** (soft-stop 409 + override-com-motivo), **ignorando** a severidade
  registrada (um "leve" de anos atrás pode ser anafilaxia hoje). Reatividade cruzada /
  match do LLM / alergia inativa → **ADVISE**.
- **Sem fabricar:** match direto roda sobre dado existente (Allergy+Drug, zero tabela
  nova). Reatividade-cruzada (A2) e interação (A3) = tabelas **curadas humanas**, inertes
  até preencher.
- **Gate generalizado:** renomear `has_blocking_dose_alert` → `has_blocking_safety_alert`;
  bloqueia em QUALQUER `AISafetyAlert(source=engine, severity=contraindication,
  status=flagged)` (dose+allergy). UI agrupa por `alert_type`. LLM (`source=llm`) nunca
  bloqueia — split anti-clobber preservado.
- **Flag própria** `allergy_safety` (default OFF) — tenants adotam em ritmos distintos
  conforme a banda de curadoria (active_ingredients, tabelas).
- **Interação single-query (A3):** `DrugInteraction.objects.filter(drug_a__in=items,
  drug_b__in=items)` UMA query, processa as arestas em memória (prescrição ~15-20 itens).
- **Sequência:** A1 (campo `active_ingredients` + `AllergyChecker` token-subset + gate
  generalizado + flag) · A2 (`AllergenCrossReactivity` curado, advise) · A3
  (`DrugInteraction` curado, single-query) · A4 (rótulos por alert_type no modal).

## Decisões a travar (eng-review) — RESOLVIDAS acima
- Algoritmo de match texto-livre (token vs substring; normalização; campo estruturado de
  ingrediente no Drug agora vs depois). **Falso-negativo é o pior caso.**
- Mapear severidade da `Allergy` → block (severe/life_threatening) vs advise (mild/moderate);
  só `status=active` conta.
- Reaproveitar `AISafetyAlert`/gate/modal vs criar superfície nova (preferência: reaproveitar).
- Flag própria `allergy_safety` vs reusar `dose_safety` (preferência: própria).
- Interação: par-a-par O(n²) na prescrição — single-query da tabela curada, sem N+1.
- Conflito com o LLM existente: engine (autoritativo) e llm (explicador) coexistem via
  `source` (mesmo split anti-clobber do dose); o gate só bloqueia em `source=engine`.

## ✅ SHIPPED (todos merged em master, flag `allergy_safety` OFF)
- **A1 #93** — motor `apps/pharmacy/services/allergy_checker.py` (token-subset
  normalizado; match direto severity-agnostic → block) + `Drug.active_ingredients`
  + orquestrador `apps/emr/services/allergy_safety.py` + **gate generalizado**
  `apps/emr/services/prescription_safety_gate.py` (sign/dispense bloqueia qualquer
  `source=engine`+`contraindication` dos wedges ligados) + flag `allergy_safety`.
- **A2 #94** — `AllergenClass` curado + verdict CROSS_REACTIVITY (advise; direto
  ainda vence).
- **A3 #95** — `DrugInteraction` curado + `find_interactions` puro (single-query) +
  alerta `drug_interaction` por item (advise / contraindicated→block).
- **A4** — frontend: `DoseSafetyModal` retitulado "Verificação de segurança" +
  `blockingKindLabel` por `blocking_kind`; índice `AI-NATIVE-WEDGES.md` vira 5 wedges.

**To go live:** ligar flag + (opcional) curar `Drug.active_ingredients`,
`AllergenClass`, `DrugInteraction` — match direto roda sobre dado existente; as
tabelas curadas são verdade humana, inertes até preencher.

## Fora de escopo (v1)
Parsing de composição multi-ingrediente a partir de texto, ATC/RxNorm, severidade de
interação dependente de dose, dedup de alérgenos por ontologia. Só match
determinístico + tabelas curadas, advise/block, flag OFF.
