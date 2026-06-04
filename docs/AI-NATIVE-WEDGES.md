# Vitali — AI-Native Interception Layer (Wedges)

> **Status:** Built, **flag-gated OFF** — pending human-supplied data before go-live.
> **Thesis:** [`VISION-AI-NATIVE.md`](./VISION-AI-NATIVE.md) ·
> **Roadmap context:** [`EPICS_AND_ROADMAP.md`](./EPICS_AND_ROADMAP.md) → "AI-Native Reframe"

This page is the single source of truth for the **seven AI-native interception
wedges** shipped this cycle. All seven are merged to master and **OFF by default**:
each is gated by a per-tenant `FeatureFlag` (default OFF) and, where it depends on
clinical / contractual / ANS reference data, that data is **human-supplied external
truth** — **none of it is invented in code.** Built ≠ live.

---

## The shared pattern

Every wedge is the same shape — the **Observe → Predict → Intercept → Learn** loop
on the spine of a real workflow, not a bolt-on report:

- **Pure deterministic engine** — authoritative, `Decimal`-only where numeric, no
  LLM in the decision path. The LLM (when present) only *explains*; it never
  decides the gate.
- **Orchestrator** — resolves inputs in single queries (no N+1), persists the
  verdict, writes the flywheel `AuditLog`.
- **Persistent alert** — a dedicated alert row (not an ephemeral cache) so the
  verdict, the override reason, and the outcome survive for learning.
- **Per-tenant feature flag, default OFF** — nothing intercepts until a tenant
  explicitly enables it.
- **Flywheel** — every verdict + override + outcome is recorded, feeding accuracy
  review and future rule tuning. The moat compounds with use.
- **Advise-vs-block posture** — clinical/operational safety decides who can be
  hard-stopped. Dose blocks (soft-stop, override-with-reason); glosa blocks only
  the highest-confidence checks; stockout never blocks (advise only — never gate a
  clinical dispense on a supply prediction); deterioration never blocks (advise /
  escalation only — never gate the recording of a vital sign); allergy direct
  matches block (soft-stop, override-with-reason), while cross-reactivity and
  most interactions advise.

> **Nothing invented; human-validated truth.** No pharmacist-validated formulary
> numbers, no ANS/contract reference values, and no establishment supply policy
> are fabricated in the codebase. Schema + engine ship; the numbers are loaded by
> a human and the flag is flipped per tenant.

---

## The seven wedges

### 1. Dose-safety — `dose_safety` (OFF)

Patient-aware medication dose-error interception at every gate of the medication
journey (prescription → pharmacy → bedside), starting with high-alert injectables.

- **Engine:** `apps/pharmacy/services/dose_checker.py` (`DoseChecker`) over
  `MedicationFormulary` / `DoseRule` — dose-engine v2 adds frequency-band /
  `dose_role` loading / enforcement-advise.
- **Orchestrator:** `apps/emr/services/dose_safety.py` (`DoseCheckService`).
- **Gate:** soft-stop (409) at `Prescription.sign` and the pharmacy `DispenseView`;
  override reuses the existing acknowledge-alert path.
- **Alert:** `AISafetyAlert` with a `source` field (`engine` vs `llm`) so the
  deterministic verdict and the LLM explainer never clobber each other.
- **Frontend:** `DoseSafetyModal`.
- **Plans:** [`plans/DOSE-SAFETY-WEDGE.md`](./plans/DOSE-SAFETY-WEDGE.md) ·
  [`plans/DOSE-FORMULARY-DRAFT.md`](./plans/DOSE-FORMULARY-DRAFT.md).
- **To go live:**
  - [ ] **Flag** `dose_safety` enabled for the tenant.
  - [ ] **Data:** pharmacist-validated formulary (`MedicationFormulary` /
    `DoseRule`) — decision **D-T1**, still **PENDING**. The production tables stay
    EMPTY until a pharmacist supplies and signs the numbers. See the
    [formulary validation package](./formulary-package/) (instructions,
    proposed CSV, and the validation PDF for the responsible pharmacist).

### 2. Glosa-interception — `glosa_safety` (OFF)

Deterministic interception of payment-denial (glosa) risk **before** a TISS
batch is sent to the payer — per-guia, not month-end report.

- **Engine:** `apps/billing/services/glosa_checker.py` (`GlosaChecker`) —
  duplicate / stale-price / non-tabulated / structural-completeness checks, plus
  clinical-compat (`TUSSCode` age/sex/CID), per-procedure ceiling, and an
  `Authorization`-requirement check.
- **Gate:** per-guia soft-stop (409) at `TISSBatchViewSet.close` — returns only
  the guias with an unacknowledged blocking alert, so the rest of the batch still
  closes; override-with-reason per guia.
- **Alert:** dedicated `GlosaSafetyAlert` (keeps the LLM `GlosaPrediction`
  artifact pure for the flywheel).
- **Supporting:** `Authorization` model; item-level `was_denied` backfill in the
  retorno parser (so a 1-of-5 denial no longer poisons the ground truth).
- **Frontend:** `GlosaSafetyModal`.
- **Plan:** [`plans/GLOSA-WEDGE.md`](./plans/GLOSA-WEDGE.md).
- **To go live:**
  - [ ] **Flag** `glosa_safety` enabled for the tenant.
  - [ ] **Data:** the highest-value checks run on the **current schema with no new
    data**. The clinical-compat / per-procedure-ceiling / authorization checks rely
    on ANS-imported `TUSSCode` attributes and per-establishment config — **external
    truth, loaded by import/config, never invented.** Until loaded those checks stay
    inert (advise-only).

### 3. Stockout-prediction — `stockout_safety` (OFF)

Predicts the day a drug/material runs out (and lots that will expire unused)
**before** it happens — proactive supply dashboard, never a dispense gate.

- **Engine:** `apps/pharmacy/services/stockout_checker.py` (`StockoutChecker`) —
  consumption velocity via 30-day SMA on dispense movements (inert if velocity 0
  or < 3 events), days-to-stockout vs lead time; FEFO expiry-waste prediction.
- **Orchestrator:** `StockoutService` (resolves history from `StockMovement`,
  persists verdict, flywheel).
- **Alert:** persistent `StockAlert` (`stockout_risk` | `expiry_waste`, severity
  **advise**).
- **Surface:** `StockRiskView` + frontend risk panel; **proactive only — no
  `DispenseView` gate** (blocking a clinical dispense on a supply prediction is
  unsafe).
- **Flywheel:** nightly grading job (`true_positive` / `intercepted` /
  `false_positive`) — see the plan for the locked ordering.
- **Plan:** [`plans/STOCKOUT-WEDGE.md`](./plans/STOCKOUT-WEDGE.md).
- **To go live:**
  - [ ] **Flag** `stockout_safety` enabled for the tenant.
  - [ ] **Data:** consumption velocity is **derived** from `StockMovement` (not
    invented). Only `lead_time_days` / `safety_stock` / `reorder_point` are
    per-establishment config — nullable and **inert** until filled. The wedge
    surfaces nothing actionable until both the flag is on and history accrues.

### 4. Clinical-deterioration — `deterioration_safety` (OFF)

Early-warning interception of clinical deterioration (sepsis / shock / respiratory
failure) via the **NEWS2** score — raises an alert when a patient's vital signs
cross the risk band, **before** the code blue. Surfaced on a clinical dashboard;
**never blocks the recording of a vital sign.**

- **Engine:** `apps/emr/services/news2.py` (`compute_news2`) — the **public,
  validated** Royal College of Physicians NEWS2 (2017) table over all 7 parameters
  (respiratory rate, SpO2 scales 1 & 2, supplemental O2, systolic BP, heart rate,
  temperature, ACVPU). **Strict:** any of the 7 missing → inert (`None`); no
  imputation. *NEWS2 is a published standard, not invented truth — unlike the dose
  numbers it ships as code citing the source.*
- **Schema:** `VitalSigns` became a time-series (`OneToOne → ForeignKey`) + the 3
  missing NEWS2 params (`respiratory_rate`, `on_supplemental_oxygen`,
  `consciousness`); `Patient.use_spo2_scale_2` (Scale 2 for target-88–92% patients,
  safe-by-default OFF).
- **Orchestrator:** `apps/emr/services/deterioration.py` (`DeteriorationService`),
  triggered by a `VitalSigns` `post_save` → `transaction.on_commit` so it can never
  block/roll back recording. De-dup: one OPEN alert per encounter, escalated only
  when the score rises; a new alert after the previous is acknowledged.
- **Alert:** persistent `DeteriorationAlert` (severity **advise** | **escalation**;
  `high` band → escalation). Partial unique index enforces one open alert/encounter.
- **Surface:** `GET /deterioration-alerts/` (sickest first) + ack endpoint;
  frontend board at `/deterioracao`. **No gate anywhere** on vitals recording.
- **Plan:** [`plans/DETERIORATION-WEDGE.md`](./plans/DETERIORATION-WEDGE.md).
- **PRs:** #87 (engine + schema) · #88 (alert + orchestrator + flag) · #89 (backend
  surface) · #90 (frontend board).
- **To go live:**
  - [ ] **Flag** `deterioration_safety` enabled for the tenant.
  - [ ] **Governance:** the NEWS2 algorithm is public/validated and ships as code;
    enabling it is a **clinical-governance** decision + an **escalation protocol**
    (who is paged at which band) — establishment config, the *routing*, not the
    math. Per-patient SpO2 Scale 2 is an explicit clinical toggle.
  - [ ] *(deferred)* **D4 outcome flywheel** — grading NEWS2 predictions against a
    real clinical outcome (ICU transfer / rapid-response call / admission) needs an
    outcome signal Vitali does **not** model yet (`Encounter.status` is only
    open/signed/cancelled). The `DeteriorationAlert` + `AuditLog` already bank every
    alert as a labelled example; grading waits on that outcome source — **not
    fabricated.**

### 5. Allergy & drug-interaction — `allergy_safety` (OFF)

Completes the medication-safety trilogy with dose: dose answers *"right amount?"*,
this answers *"safe for **this** patient at all?"*. Adds the deterministic engine
behind the `AISafetyAlert` `allergy` / `drug_interaction` types (until now
LLM-only) and a soft-stop at prescription **sign** / **dispense**.

- **Engine:** `apps/pharmacy/services/allergy_checker.py` (`AllergyChecker` +
  `find_interactions`) — **normalized token-subset** matching (casefold + strip
  accents + drop dose/connector noise; no raw substring). Three checks: **direct
  allergy** (allergen tokens ⊆ drug tokens → **block**, severity-agnostic);
  **cross-reactivity** (curated `AllergenClass` links allergen + drug → **advise**);
  **drug-drug interaction** (curated `DrugInteraction` pair both present → advise,
  or block if `contraindicated`).
- **Schema:** `Drug.active_ingredients` (curated INN list; empty → name/generic
  fallback). `AllergenClass` + `DrugInteraction` curated tables.
- **Orchestrator:** `apps/emr/services/allergy_safety.py` (`AllergySafetyService`)
  — resolves active allergies + curated tables in single queries; writes
  engine-sourced alerts (override-preservation); flywheel `AuditLog`.
- **Gate:** the sign/dispense soft-stop was **generalized**
  (`apps/emr/services/prescription_safety_gate.py`) to block on ANY engine
  contraindication across enabled wedges (dose + allergy + interaction), keeping
  each wedge's "flag OFF → gate released". Frontend reuses `DoseSafetyModal`
  (retitled "Verificação de segurança"; rows labelled by `blocking_kind`).
- **Plan:** [`plans/ALLERGY-INTERACTION-WEDGE.md`](./plans/ALLERGY-INTERACTION-WEDGE.md).
- **PRs:** #93 (engine + gate) · #94 (cross-reactivity) · #95 (interactions) · A4 (modal labels).
- **To go live:**
  - [ ] **Flag** `allergy_safety` enabled for the tenant.
  - [ ] **Data:** direct allergy match runs on **existing** `Allergy` + `Drug` data
    (curating `Drug.active_ingredients` sharpens it). Cross-reactivity
    (`AllergenClass`) and interactions (`DrugInteraction`) are **human-curated**
    tables — inert until populated, never invented.
  - [ ] **Curation guideline (alert-fatigue):** record allergens as **full
    ingredient names**, not bare salts/radicals. The matcher is normalized
    token-subset, so an over-generic single-token allergen (e.g. just `"sulfato"`)
    will hard-block any drug containing that token (e.g. `"Sulfato de Magnésio"`).
    This is fail-safe (it over-blocks and is overridable-with-reason, never
    under-blocks) but causes avoidable alert fatigue — populate `active_ingredients`
    and use specific allergen names to keep blocks precise.

### 6. No-show prediction — `no_show_prediction` (OFF)

Predicts which upcoming appointments will no-show so reception can intercept
*before* the empty slot (confirm actively / overbook / offer the waitlist).
**The only wedge that goes live with NO curated data** — the risk is DERIVED from
each patient's own appointment history, like stockout derives velocity from
movements. Advise/operational — never blocks booking or check-in.

- **Engine:** `apps/emr/services/no_show_checker.py` (`score_no_show`) — transparent
  **multiplicative-odds** model (not ML): `base = (no_shows+2)/(terminal+10)`
  [Beta(2,8) prior → 20% baseline]; `score = odds/(1+odds)` with explainable odds
  modifiers (no-confirm-after-reminder ×1.6, lead ≥30d ×1.4, ≥2 consecutive prior
  no-shows ×2.0, self-serve channel ×1.2, return ×1.15). Bands low/medium/high.
  **INERT** (no row) below 5 terminal appointments — never brand a low-history
  patient on the prior alone.
- **Orchestrator:** `apps/emr/services/no_show.py` (`NoShowService`) — nightly
  `evaluate_window` over the upcoming window in **2 bounded queries** (no N+1);
  leakage guards (history strictly prior; `cancelled` excluded from numerator AND
  denominator). `grade_predictions` is the 4-way flywheel (cancelled excluded).
- **Persistence/surface:** `NoShowRisk` (per-appointment, Decimal score, band,
  breakdown, `suggested_action`); `GET /no-show-risk/` + ack endpoint; front-desk
  panel at `/faltas`. Two nightly celery tasks (evaluate 02:00, grade 03:30).
- **Plan:** [`plans/NOSHOW-WEDGE.md`](./plans/NOSHOW-WEDGE.md).
- **PRs:** #98 (engine + model) · #99 (orchestrator + job + flywheel) · N3 (surface).
- **To go live:**
  - [ ] **Flag** `no_show_prediction` enabled + the nightly beat tasks running.
  - [ ] **No curated data needed** — the risk is derived from existing appointment
    history; band cutoffs are establishment-tunable config (sensible defaults).
    The wedge is simply inert per-patient until ≥5 terminal appointments accrue.

### 7. Controlled-substance diversion — `controlled_safety` (OFF)

Detects anomalous controlled-substance dispensing patterns (Portaria 344/SNGPC
context) — early refills, doctor-shopping, quantity escalation — and raises a
compliance alert. **ADVISE/compliance only — never blocks a controlled
dispensation** (the existing `dispense_controlled` perm + mandatory-notes gate
governs the act; a false-positive block would deny a patient a legitimate
controlled med). Risk derived from dispensation history; no invented data.

- **Engine:** `apps/pharmacy/services/controlled_checker.py` — three deterministic,
  prior-only, per-class/per-drug signals: **refill_too_soon** (same drug, a
  *different* prescription within the drug's `min_refill_interval_days`; the
  fragile `qty/(freq×dose)` days-supply formula is deliberately avoided — dose_unit
  is mass-only while dispense quantity is countable), **multiple_prescribers** (≥3
  distinct prescribers, same controlled class, 90d), **quantity_escalation** (last
  3 same-drug fills strictly increasing). Inert when data absent.
- **Orchestrator:** `apps/pharmacy/services/controlled_safety.py` — `Dispensation`
  post_save → `on_commit` (after the 201, never blocks); resolves prior history in
  2 bounded queries; persists a `ControlledAlert` per signal; AuditLog flywheel.
- **Schema:** `Drug.min_refill_interval_days` (null → refill inert; no honest
  public default). `ControlledAlert` (unique `(dispensation, signal_kind)`).
- **Surface:** `GET /pharmacy/controlled/alerts/` + ack; compliance panel at
  `/farmacia/controlados`. `pharmacy.read`.
- **Plan:** [`plans/CONTROLLED-DIVERSION-WEDGE.md`](./plans/CONTROLLED-DIVERSION-WEDGE.md).
- **PRs:** #102 (engine + model) · #103 (orchestrator + hook + flywheel) · C3 (surface).
- **To go live:**
  - [ ] **Flag** `controlled_safety` enabled.
  - [ ] **Mostly no curated data** — signals derive from dispensation history. Only
    the refill signal needs a per-drug `min_refill_interval_days` (inert until set,
    no invented default). The K=3 / 90d doctor-shopping thresholds are operational
    defaults, **not** ANVISA/Portaria-344 rules.

---

## Honesty contract

- All seven flags ship **OFF**. No wedge is live or enabled by default.
- No pharmacist / ANS / contract numbers exist yet in production — they are
  **pending and human-gated** (dose D-T1 explicitly blocks dose go-live).
- The deterministic engine is authoritative; the LLM only explains.
- This is a **built** layer, not a **live** one. Built ≠ live.
</content>
</invoke>
