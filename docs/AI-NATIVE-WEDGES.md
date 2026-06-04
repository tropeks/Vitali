# Vitali — AI-Native Interception Layer (Wedges)

> **Status:** Built, **flag-gated OFF** — pending human-supplied data before go-live.
> **Thesis:** [`VISION-AI-NATIVE.md`](./VISION-AI-NATIVE.md) ·
> **Roadmap context:** [`EPICS_AND_ROADMAP.md`](./EPICS_AND_ROADMAP.md) → "AI-Native Reframe"

This page is the single source of truth for the **three AI-native interception
wedges** shipped this cycle. All three are merged to master and **OFF by default**:
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
  clinical dispense on a supply prediction).

> **Nothing invented; human-validated truth.** No pharmacist-validated formulary
> numbers, no ANS/contract reference values, and no establishment supply policy
> are fabricated in the codebase. Schema + engine ship; the numbers are loaded by
> a human and the flag is flipped per tenant.

---

## The three wedges

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

---

## Honesty contract

- All three flags ship **OFF**. No wedge is live or enabled by default.
- No pharmacist / ANS / contract numbers exist yet in production — they are
  **pending and human-gated** (dose D-T1 explicitly blocks dose go-live).
- The deterministic engine is authoritative; the LLM only explains.
- This is a **built** layer, not a **live** one. Built ≠ live.
</content>
</invoke>
