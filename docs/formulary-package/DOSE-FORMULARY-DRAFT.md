# Formulário de Dose — RASCUNHO DE PESQUISA (D-T1)

> [!CAUTION]
> **RASCUNHO — PENDENTE DE VALIDAÇÃO FARMACÊUTICA. NÃO SEMEAR. NÃO LIGAR A FLAG `dose_safety`.**
>
> Estes números foram **pesquisados** em fontes de referência (não inventados), por
> dois modelos independentes (Claude via WebSearch + Gemini via `agy`) e cruzados.
> São **faixas de referência para acelerar a revisão** — um farmacêutico clínico
> DEVE validar cada valor contra o protocolo institucional e a bula do produto
> efetivamente estocado **antes** de qualquer seed em produção. O motor de dose é
> autoritativo apenas sobre números que um humano validou (decisão D-T1).

## Lista proposta (provisória — o farmacêutico confirma o escopo)

8 injetáveis high-alert que **encaixam no modelo por-administração** do motor
(bolus IV/IM). Infusões contínuas dosadas em `mcg/kg/min` (noradrenalina,
dopamina) **não** cabem no schema atual e ficam fora desta leva.

1. Vancomicina · 2. Gentamicina · 3. Amicacina · 4. Morfina (sulfato) ·
5. Fentanila (citrato) · 6. Midazolam · 7. Adrenalina (IM, anafilaxia) ·
8. Cetamina/Quetamina (IV)

---

## ⚠️ Avisos globais (ler primeiro — valem para o seed inteiro)

- **Fentanila é dosada em MCG, não mg.** Adrenalina em anafilaxia é sub-miligrama.
  Mistura mg↔mcg = erro de 1000×. O motor já bloqueia mismatch dentro da mesma
  família de massa — mas o `dose_unit` de cada regra precisa estar correto.
- **Adrenalina: 1:1000 (1 mg/mL, IM/anafilaxia) ≠ 1:10000 (0,1 mg/mL, IV/parada).**
  Confundir = erro 10×, frequentemente fatal. Esta leva cobre **só** o 1:1000 IM.
- **Aminoglicosídeos (genta, amica) e vancomicina exigem ajuste renal + TDM.** Uma
  faixa mg/kg plana é só um **teto de triagem**, não a dose individualizada.
- **Opioides/sedativos (morfina, fentanila, midazolam, cetamina) não têm teto
  farmacológico fixo.** O "máximo" abaixo é um limiar de *alerta* de referência
  para paciente virgem de opioide — NÃO um bloqueio físico. Titulação com
  monitorização governa a dose real.

## 🚩 Limitações do motor (atualizado — dose-engine v2)

> [!NOTE]
> **dose-engine v2** adicionou três eixos ao `DoseRule`, que removem três das
> limitações abaixo. O motor agora modela:
> - **AXIS 1 — banda de frequência** (`freq_min_per_day`/`freq_max_per_day`):
>   duas regras coexistem para a mesma droga/idade, desambiguadas pela frequência
>   prescrita. Resolve **tradicional vs intervalo-estendido** (genta/amica):
>   regra estendida (freq 1–1, mg/kg maior) + regra tradicional (freq 2–4, mg/kg
>   menor). **Fail-safe:** se a regra tem banda de frequência e a frequência
>   prescrita é desconhecida, a regra NÃO casa → cai em `NO_RULE_MATCH` (alerta),
>   nunca uma seleção errada.
> - **AXIS 2 — `dose_role` (loading vs maintenance)** no `DoseRule` e no
>   `PrescriptionItem`: uma regra de **loading** só é selecionada quando o
>   prescritor marca explicitamente o item como loading. Resolve a
>   **vancomicina** (loading 25–30 mg/kg). **Fail-safe:** dose de magnitude de
>   loading sem a marcação é checada contra a banda (menor) de manutenção →
>   `OUT_OF_RANGE` (super-alarma; o prescritor corrige ou marca loading + override).
> - **AXIS 3 — `enforcement` (block vs advise)**: numa regra `advise`, um
>   `OUT_OF_RANGE` (faixa, teto absoluto OU teto diário) vira **alerta não
>   bloqueante** (caution), não um 409. Resolve **opioides/sedativos** sem teto
>   farmacológico rígido — o "máximo" é limiar de alerta, não bloqueio físico.
>   `WEIGHT_GATE` e `UNIT_MISMATCH` **continuam bloqueando** independentemente de
>   `enforcement` (não se dosa por-kg sem peso, e mismatch de unidade é sempre
>   perigoso).

O motor ainda **não** modela:

- **Ajuste renal / TDM.** As faixas mg/kg continuam sendo **tetos de triagem**,
  não a dose individualizada (AUC/MIC, clearance renal, níveis séricos).
- **Tolerância a opioide** como dado estruturado do paciente (a regra `advise`
  apenas torna o teto um alerta; não distingue paciente virgem de tolerante).

→ **Decisão pro farmacêutico:** as drogas de paradigma duplo agora cabem
(genta/amica via banda de frequência, vanco via `dose_role`, opioides via
`advise`). Ainda assim, **toda** faixa é teto de triagem até validação humana —
o ajuste renal/TDM permanece responsabilidade clínica fora do motor.

---

## Tabelas por droga — mapeadas aos campos de `DoseRule`/`MedicationFormulary`

Convenção dos campos: `basis` (per_kg|fixed) · `dose_unit` · `min_per_kg`/`max_per_kg`
(mg/kg por administração) · `absolute_max_dose` (teto absoluto por administração) ·
`max_per_day` · `route` · força do frasco (BR). **Coluna "Claude" e "agy" = fontes
independentes; "CONFIRMAR" = decisão do farmacêutico.**

### 1. Vancomicina (IV)
| Campo | Claude (WebSearch) | agy (Gemini) | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg | mg | ☐ |
| basis | per_kg | per_kg | ☐ |
| min–max por kg/dose | 10–20 mg/kg | 10–20 mg/kg | ☐ |
| absolute_max_dose | 2000 mg | 2000 mg | ☐ (concordam) |
| **max_per_day** | **6000 mg** | **4000 mg (adulto) / 60 mg/kg/d (peds)** | 🚩 **DIVERGE: 6 g vs 4 g** |
| route / frasco | IV · 500 mg, 1 g pó | IV · 500 mg, 1 g | ☐ |
- Fontes: DoseMeRx; GoodRx/Lexicomp; PMC7439954; bula ANVISA. **Loading 25–30 mg/kg não modelado.** AUC/MIC 400–600 individualiza.

### 2. Gentamicina (IV/IM)
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg | mg | ☐ |
| min–max por kg/dose (tradicional) | 2–2,5 mg/kg | 2–2,5 mg/kg | ☐ |
| min–max por kg/dose (estendido) | 5–7 mg/kg | 5–7,5 mg/kg | ☐ |
| **absolute_max_dose** | **sem teto mg universal (mg/kg+renal)** | **700 mg (≈100 kg estendido)** | 🚩 **DIVERGE: definir teto** |
| **max_per_day** | **5 mg/kg/d (grave)** | **7,5 mg/kg/d** | 🚩 **DIVERGE: 5 vs 7,5 mg/kg/d** |
| route / frasco | IV/IM · 40 mg/mL | IV/IM · 10/40/80 mg | ☐ |
- 🚩 **Dois paradigmas (tradicional vs estendido) — escolher um pro v1.** Neonato: intervalo estendido por idade gestacional. Fontes: Pfizer Medical; PDR; Drugs.com/Lexicomp.

### 3. Amicacina (IV/IM)
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg | mg | ☐ |
| por kg/dose (1×/dia) | 15 mg/kg (FC 30–35) | 15–20 mg/kg | ☐ |
| por kg/dose (tradicional) | 7,5 mg/kg 12/12h | 5–7,5 mg/kg | ☐ |
| absolute_max_dose | 1500 mg | 1500 mg | ☐ (concordam) |
| max_per_day | 1500 mg (≤15 mg/kg/d) | 1500 mg | ☐ (concordam) |
| route / frasco | IV/IM · 500 mg | IV/IM · 100/500 mg | ☐ |
- 🚩 Dois paradigmas. FC excede a faixa padrão legitimamente. Fontes: Pediatric Oncall; Drugs.com; PDR.

### 4. Morfina sulfato (IV)
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg | mg | ☐ |
| por kg/dose (peds) | 0,05–0,1 (até 0,3 por idade) | 0,05–0,2 mg/kg | ☐ |
| adulto fixo/dose | 2–10 mg | 2–10 mg | ☐ (concordam) |
| **absolute_max_dose (virgem)** | **~10 mg (cap 1–5 anos)** | **~15 mg** | 🚩 **DIVERGE: 10 vs 15 mg** |
| max_per_day | sem teto (titular) | sem teto (flag >60 mg/d IV virgem) | ☐ |
| route / frasco | IV/IM/SC · 10 mg/mL | IV/IM/SC · 10 mg/mL | ☐ |
- 🚩 **Sem teto real (tolerância). "Máx" deve ser ALERTA, não bloqueio rígido.** >50 kg usa dose fixa adulto, não mg/kg. Fontes: FDA label; StatPearls; Children's MN.

### 5. Fentanila citrato (IV) — **MCG**
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| **dose_unit** | **mcg** | **mcg** | ☐ (crítico) |
| por kg/dose (peds) | 1–2 mcg/kg | 1–2 mcg/kg | ☐ |
| adulto fixo/dose | 25–100 mcg | 25–100 mcg | ☐ |
| absolute_max_dose (analgesia) | ~200 mcg | 100–200 mcg | ☐ (concordam; indução ≫) |
| max_per_day | sem teto (titular) | sem teto | ☐ |
| route / frasco | IV · 50 mcg/mL base | IV · 50 mcg/mL | ☐ |
- 🚩 **Trap BR: bula lista 78,5 mcg/mL de citrato = 50 mcg/mL de base. A dose é pela BASE (50 mcg/mL).** Fontes: FDA label; ABL/Cristália bula; StatPearls.

### 6. Midazolam (IV)
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg | mg | ☐ |
| por kg/dose (peds) | 0,05–0,1 mg/kg | 0,05–0,1 mg/kg | ☐ (concordam) |
| adulto fixo/dose | 1–2,5 mg | 1–5 mg | ☐ |
| **absolute_max_dose** | **6 mg (6m–5a) / 10 mg (6–12a)** | **5–7,5 mg** | 🚩 **DIVERGE: revisar cap por idade** |
| max_per_day | cap de titulação procedural | ~20–30 mg/d (bolus) | ☐ |
| route / frasco | IV/IM · 1 e 5 mg/mL | IV/IM · 1 e 5 mg/mL | ☐ |
- 🚩 Reduzir em idoso/debilitado + sinergia com opioides. Duas concentrações no mercado (1 vs 5 mg/mL). Fontes: FDA label; protocolos BR.

### 7. Adrenalina (IM, anafilaxia) — **UNIT-CRITICAL**
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg (de 1:1000 = 1 mg/mL) | mg | ☐ |
| por kg/dose (peds) | 0,01 mg/kg | 0,01 mg/kg | ☐ (concordam) |
| adulto fixo/dose | 0,3–0,5 mg | 0,3–0,5 mg | ☐ (concordam) |
| **absolute_max_dose** | **0,3 mg (<30 kg/pré-púbere) / 0,5 mg (adulto)** | **0,5 mg** | 🚩 **DIVERGE: cap pré-púbere 0,3 vs 0,5** |
| max_per_day | N/A (repetir 5–15 min) | N/A | ☐ |
| route / frasco | **IM** · 1 mg/mL (1:1000) | **IM** · 1 mg/mL | ☐ |
- 🚩 **Só 1:1000 IM. Nunca 1:10000 IV nesta regra.** Fontes: Merck Manual; WAO (PMC10990378); SBP/ASBAI; bula PedB.

### 8. Cetamina/Quetamina (IV)
| Campo | Claude | agy | CONFIRMAR |
|---|---|---|---|
| dose_unit | mg | mg | ☐ |
| por kg/dose (IV, sedação/indução) | 1–1,5 (repete 0,5) | 1–2 mg/kg | ☐ |
| **absolute_max_dose** | **4,5 mg/kg IV (máx label)** | **~150 mg fixo** | 🚩 **DIVERGE: por-kg vs fixo** |
| max_per_day | não fixo | N/A | ☐ |
| route / frasco | IV (IM 4–13 mg/kg) · 50 mg/mL | IV · 50 mg/mL | ☐ |
- 🚩 **Via muda a dose 3–10× (IV 1–2 vs IM 4–13 mg/kg) — `route` obrigatório.** Fontes: Drugs.com; LITFL; protocolos BR ICU.

---

## 🚩 Divergências entre fontes — revisar PRIMEIRO (maior consequência → menor)

1. **Adrenalina** — cap pré-púbere **0,3 mg (SBP/Claude) vs 0,5 mg (agy)**. Peds, alta consequência.
2. **Fentanila** — confirmar `dose_unit = mcg` e a concentração **base 50 mcg/mL** (não 78,5 do citrato).
3. **Gentamicina** — teto absoluto por administração (**indefinido vs 700 mg**) e diário (**5 vs 7,5 mg/kg/d**); e qual paradigma (tradicional/estendido) entra no v1.
4. **Vancomicina** — teto diário **6 g vs 4 g (adulto)**.
5. **Morfina** — cap por administração em virgem **10 vs 15 mg** (e confirmar que é alerta, não bloqueio).
6. **Midazolam** — cap absoluto por idade (**6/10 mg vs 5–7,5 mg**).
7. **Cetamina** — teto como **4,5 mg/kg vs ~150 mg fixo**.

## Aptidão ao schema (atualizado — dose-engine v2)

Com os três eixos novos (banda de frequência, `dose_role`, `enforcement`), todas
as 8 drogas **encaixam** no schema. A coluna abaixo indica QUAL eixo cada
paradigma duplo usa. (Os números continuam pendentes de validação farmacêutica.)

| Droga | Encaixa? | Como (eixo v2) |
|---|---|---|
| Adrenalina (IM) | ✅ | faixa única clara |
| Fentanila | ✅ | faixa única (mcg) — travar unidade/base |
| Midazolam | ✅ | procedural — cap por idade |
| Morfina | ✅ | **AXIS 3** `enforcement="advise"` (teto = alerta, não bloqueio) |
| Cetamina | ✅ | faixa única com `route` travado |
| Vancomicina | ✅ | **AXIS 2** `dose_role` (loading 25–30 mg/kg + manutenção) |
| Gentamicina | ✅ | **AXIS 1** banda de frequência (estendido 1×/d + tradicional 2–4×/d) |
| Amicacina | ✅ | **AXIS 1** banda de frequência (1×/d + tradicional) |

> [!CAUTION]
> "Encaixa no schema" ≠ "pronto pra produção". Cada faixa segue sendo **teto de
> triagem** pendente de validação humana; ajuste renal/TDM permanece fora do
> motor. Continua valendo o **NÃO SEMEAR / NÃO LIGAR A FLAG** do topo deste doc.

## Como validar (checklist do farmacêutico)

- [ ] Confirmar a **lista** de 8 (ou ajustar escopo v1).
- [ ] Resolver as **7 divergências** acima.
- [ ] Para cada droga, preencher a coluna CONFIRMAR contra o **protocolo da casa** e a **bula do produto estocado** (forças/concentrações variam por fabricante).
- [ ] Decidir, por droga de paradigma duplo, qual faixa entra no v1 (ou adiar).
- [ ] Marcar quais `absolute_max_dose` são **bloqueio** vs **alerta** (opioides → alerta).
- [ ] Definir D-T2 (janela de peso, default 90 dias).
- [ ] Só então: seed do `MedicationFormulary`/`DoseRule` + ligar a flag `dose_safety` por tenant.

---

*Pesquisa cross-model (Claude WebSearch + Gemini/agy), junho/2026. Fontes completas
listadas por droga acima. Nenhum número aqui é autoritativo até validação humana.*
