# Validação do Formulário de Dose — Vitali (D-T1)

**Para:** Farmacêutico(a) clínico(a) responsável
**De:** Equipe Vitali
**Assunto:** Validação das faixas de dose do verificador automático de doses (injetáveis high-alert)

---

## 1. O que é isto, em uma frase

O Vitali tem um **verificador automático de dose** que, na prescrição e na
dispensação, compara a dose prescrita com a faixa segura para o **peso/idade**
do paciente e **interrompe** (com pedido de justificativa) doses fora da faixa.
Ele **só funciona com números que você validar.** Hoje o sistema está
**desligado** e **sem nenhum número clínico** — este pacote é para você preencher
e devolver os números que o sistema vai usar.

> ⚠️ **Contrato de segurança:** nenhuma destas faixas entra em produção até a sua
> assinatura nesta folha. Os valores **pré-preenchidos** na planilha foram
> **pesquisados** em referências (Lexicomp/UpToDate, FDA, BNFc, Merck, SBP/ASBAI,
> bulas ANVISA) por duas ferramentas independentes e **cruzados** — são um
> **ponto de partida para acelerar a sua revisão, não verdade clínica.** Confira
> cada valor contra o protocolo da casa e a bula do produto efetivamente
> estocado.

---

## 2. O que pedimos de você (≈ o trabalho)

Na planilha **`formulario-doses-PROPOSTO.csv`** (abre no Excel/Google Sheets),
cada linha é uma **regra de dose proposta**. Para cada linha:

1. Confira os números pré-preenchidos.
2. Preencha **`VALIDADO_S_N`** → `S` (aceito como está) ou `N` (precisa mudar).
3. Se `N`, escreva o número certo em **`VALOR_CORRIGIDO`** (ex.: `max_por_dia=6000`).
4. Use **`FONTE_OBS_FARMACEUTICO`** para a fonte/protocolo que você usou ou qualquer ressalva.
5. Assine a folha (seção 6).

**Prioridade:** comece pelas **7 divergências** da seção 4 — são onde as fontes
discordaram e a sua decisão é mais necessária.

---

## 3. O que cada coluna significa (o sistema modela 3 eixos)

| Coluna | O que é |
|---|---|
| `basis` | `per_kg` (faixa por peso, em mg/kg) ou `fixed` (faixa fixa em mg, independente do peso) |
| `min_por_kg` / `max_por_kg` | faixa por kg por administração (quando `basis=per_kg`) |
| `min_por_dose` / `max_por_dose` | faixa fixa por administração (quando `basis=fixed`) |
| `absolute_max_dose` | **teto absoluto por administração** — nunca ultrapassado, **sempre bloqueia** (pega erro de peso digitado errado). Obrigatório. |
| `max_por_dia` | teto da dose diária (dose × frequência) |
| `freq_min_dia`/`freq_max_dia` | **Eixo 1:** faixa de frequência a que a regra se aplica → permite **2 regras** para a mesma droga: ex. gentamicina **estendido** (1×/dia) vs **tradicional** (8/8h) |
| `dose_role` | **Eixo 2:** `maintenance` (manutenção) ou `loading` (ataque). A regra de **ataque** só é usada se o prescritor marcar a dose como ataque → resolve a vancomicina |
| `enforcement` | **Eixo 3:** `block` (bloqueia) ou `advise` (só **alerta**). Use `advise` para opioides/sedativos **sem teto rígido** (titulação) — o "máximo" vira alerta, não bloqueio. **Mesmo em `advise`, o `absolute_max_dose` e o peso ausente continuam bloqueando.** |
| `idade_min_dias`/`idade_max_dias` | faixa etária **em dias** (ex.: 18250 ≈ 50 anos). Vazio = sem limite |

---

## 4. 🚩 As 7 decisões prioritárias (divergências entre fontes)

Ordenadas por consequência. O valor na planilha é o **mais conservador**; confirme ou corrija.

1. **Adrenalina — teto pediátrico:** proposto **0,3 mg** (pré-púbere, SBP) vs 0,5 mg. *(linha Adrenalina PEDS)*
2. **Fentanila — unidade/concentração:** confirmar `dose_unit = mcg` e que a concentração é a **base 50 mcg/mL** (não os 78,5 mcg/mL do citrato na bula).
3. **Gentamicina — teto absoluto e diário:** teto por dose **indefinido vs 700 mg**; diário **5 vs 7,5 mg/kg/dia**.
4. **Vancomicina — teto diário:** proposto **4000 mg** vs 6000 mg.
5. **Morfina — teto por dose (virgem):** proposto **10 mg** vs 15 mg (e confirmar que é **alerta**, não bloqueio).
6. **Midazolam — teto por idade:** 6 mg (6m–5a) vs 10 mg (6–12a).
7. **Cetamina — teto:** 4,5 mg/kg (label) vs ~150 mg fixo (proposto 150).

---

## 5. Escopo e limites (confirme/ajuste)

- **Lista (8 injetáveis, provisória):** Vancomicina · Gentamicina · Amicacina ·
  Morfina · Fentanila · Midazolam · Adrenalina (1:1000 IM) · Cetamina.
  **Pode adicionar/remover** — anote na folha.
- **Fora do escopo do motor hoje (responsabilidade clínica, não automatizada):**
  - **Ajuste renal / TDM** (aminoglicosídeos, vancomicina) — as faixas são **teto
    de triagem**, não a dose individualizada por clearance/níveis.
  - **Neonatos** — intervalos por idade gestacional; trate como faixa etária
    separada se quiser cobrir (ou deixe fora da v1).
  - **Infusões contínuas** (mcg/kg/min) — não modeladas.
- O detalhamento por droga, com **fontes citadas**, está em
  `DOSE-FORMULARY-DRAFT.md` (mesmo diretório).

---

## 6. Aprovação (trilho de auditoria)

> Ao assinar, autorizo o uso das faixas validadas nesta planilha pelo verificador
> de dose do Vitali, ciente de que são **teto de triagem** e não substituem o
> julgamento clínico, o ajuste renal/TDM nem a conferência da bula do produto.

| Campo | |
|---|---|
| Farmacêutico(a) | __________________________________ |
| CRF | __________________________________ |
| Estabelecimento / tenant | __________________________________ |
| Data | ______ / ______ / __________ |
| Assinatura | __________________________________ |
| Versão da planilha validada | __________________________________ |

---

*Depois de devolvida e assinada: a equipe Vitali faz o seed do `MedicationFormulary`/`DoseRule`
com os valores validados e liga a flag `dose_safety` para o seu tenant. Antes disso, o
verificador permanece desligado.*
