# Dose-Safety Wedge — Locked Plan

> **Status:** Locked by engineering review | **Date:** 2026-06 | **Owner:** Eng
> **Thesis link:** [`docs/VISION-AI-NATIVE.md`](../VISION-AI-NATIVE.md) — the
> landing wedge is **medication dose-error interception, patient-aware**:
> software that says "stop: this will harm the patient, now" at every gate of
> the medication journey (prescription → pharmacy → bedside administration),
> starting with **injectables** (highest risk, highest lethality).

This document is the locked, end-to-end plan for the dose-safety wedge. It is
the source of truth for the 3-PR sequence, the architecture locks, the known
critical gaps, and the open product/clinical decisions.

> **⚠️ Clinical dose numbers are NOT invented anywhere in this codebase.** The
> curated formulary (≈8 high-alert injectable drugs, their canonical strengths,
> and their dose bands) is **pharmacist-supplied external truth**. It lands with
> PR B. PR A is **pure schema** — the tables exist, but carry no clinical figures.

---

## 1. The 3-PR sequence

### PR A — Structured data foundation (this PR) — pure schema
- **`pharmacy.MedicationFormulary`** (OneToOne→`Drug`): the curated, dose-checkable
  subset. The *existence* of a row is the "is this drug dose-checkable?" predicate.
  Holds canonical strength (value+unit), optional volume (per-mL injectables),
  route, `is_injectable`, `is_high_alert`.
- **`pharmacy.DoseRule`** (FK→`MedicationFormulary`): one shape for BOTH pediatric
  `per_kg` bands AND adult `fixed` range+max. `max_per_dose` is the only mandatory
  numeric field — the absolute ceiling (see §3).
- **`emr.PrescriptionItem`** gains structured dose fields (`dose_amount`,
  `dose_unit`, `route`, `frequency_per_day`) — all nullable/blank; existing rows
  and non-formulary drugs are unaffected. **No free-text parsing** of
  `dosage_instructions`.
- **`emr.AISafetyAlert`** gains a `source` field and `unique_together` becomes
  `(prescription_item, alert_type, source)` — the critical idempotency fix (§4,
  gap #1). **Fixed in PR A.**
- No dose engine, no enforcement, no clinical numbers.

### PR B — Deterministic engine + soft-stop enforcement + weight-gate + flywheel
- **`DoseChecker` engine** (deterministic, authoritative): given a
  `PrescriptionItem` whose `drug` has a `MedicationFormulary` row, resolves the
  applicable `DoseRule` (by age/weight band + route), computes the patient-specific
  dose, and returns a verdict from the fail decision table (§3).
- **Soft-stop enforcement** at `Prescription.sign()` and the pharmacy
  `DispenseView`: an unacknowledged blocking dose verdict raises the gate; the
  engine writes its verdict to an `AISafetyAlert` with `source="engine"`.
  Acknowledging a `dose` alert raises severity to `contraindication` (soft-stop:
  prescriber may proceed only with an explicit override reason).
- **Weight-gate:** if the patient has no fresh weight (see D-T2), a `per_kg`
  drug cannot be dose-checked → `WEIGHT_GATE` (block until weight is captured).
- **Flywheel:** every verdict + override is recorded, feeding accuracy review and
  future rule tuning.
- **Requires pharmacist-supplied dose numbers** (D-T1) before it can ship.

### PR C — Frontend
- Surface dose badges, the soft-stop dialog, override-reason capture, and the
  weight-gate prompt in the prescription and dispense UIs.

---

## 2. Architecture locks

1. **Separate `MedicationFormulary` table** (not columns on `Drug`). The curated
   clinical truth is decoupled from the general catalog; row existence is the
   dose-checkable predicate.
2. **Structured dose fields, NOT parsing.** `PrescriptionItem` carries explicit
   `dose_amount`/`dose_unit`/`route`/`frequency_per_day`. We never parse
   `dosage_instructions` free text to derive a dose.
3. **Single `DoseRule` basis schema** handling `per_kg` and `fixed` in one shape,
   with a **mandatory absolute `max_per_dose`** (§3).
4. **Deterministic engine authoritative; LLM explains only.** The `DoseChecker`
   verdict (`source="engine"`) is the gate decision. The LLM (`source="llm"`)
   only produces a human-readable explanation; it never decides the gate.
5. **`source` field decouples engine vs LLM rows.** Two `AISafetyAlert` rows for
   the same `(prescription_item, "dose")` coexist — one per source — so neither
   clobbers the other (§4, gap #1).
6. **Fail decision table** (PR B), driven by the engine verdict:

   | Verdict          | Gate behavior              |
   |------------------|----------------------------|
   | `OUT_OF_RANGE`   | **block** (soft-stop)      |
   | `WEIGHT_GATE`    | **block** (soft-stop)      |
   | `DATA_MISSING`   | advisory (warn, allow)     |
   | `ENGINE_ERROR`   | advisory (warn, allow)     |
   | `NOT_APPLICABLE` | pass — no badge            |

   `NOT_APPLICABLE` = drug has no `MedicationFormulary` row → not dose-checkable.
   Soft-stop = the prescriber/pharmacist may proceed by acknowledging the alert
   with an override reason; acknowledgement raises the alert severity to
   `contraindication` and is recorded.

---

## 3. The mandatory absolute `max_per_dose`

`DoseRule.max_per_dose` is **NOT NULL** — the only required numeric field on the
rule. It is the absolute single-dose ceiling expressed in `dose_unit`.

For `basis="per_kg"` rules it is **still an absolute cap, not a per-kg figure.**
This is deliberate: a per-kg calculation multiplies by patient weight, so a
**weight-entry typo** (e.g. 70 kg typed as 700 kg, or a kg/lb mixup) would
otherwise sail past a purely per-kg check and produce a lethal dose. The
absolute ceiling catches that class of error regardless of the per-kg math.
(See gap #4.)

---

## 4. The 4 critical gaps

1. **Override-clobber — FIXED in PR A.** Previously `AISafetyAlert.unique_together`
   was `(prescription_item, alert_type)`. PR B's engine writes `alert_type="dose"`;
   an `update_or_create` keyed on that pair would **overwrite** a previously
   acknowledged/overridden LLM `dose` alert, wiping `override_reason` /
   `acknowledged_at`. Fix: add `source` (`TextChoices{llm,engine}`, default
   `"llm"`) and key uniqueness on `(prescription_item, alert_type, source)`. The
   engine verdict row and the LLM explainer row are now independent. Existing rows
   backfill to `source="llm"` via the AddField default; the migration is reversible.
2. **Unit coercion — PR B.** Prescribed `dose_unit` (e.g. mg) vs formulary
   strength unit (mg, mcg, g, mEq, unit) vs rule `dose_unit` must be coerced to a
   common basis before comparison. Mismatched/uncoercible units → `DATA_MISSING`
   (advisory), never a silent wrong comparison.
3. **Max-daily — PR B.** `frequency_per_day × dose_amount` vs
   `DoseRule.max_per_day`. Captured in the schema (PR A) but enforced in PR B.
4. **Weight-typo absolute floor — PR B.** The absolute `max_per_dose` ceiling on
   `per_kg` rules (see §3) is what catches weight-entry typos. The field exists in
   PR A; the engine that enforces it is PR B.

---

## 5. Open product / clinical decisions

- **D-T1 — Formulary content (PENDING PHARMACIST).** The ≈8 high-alert injectable
  drugs, their canonical strengths, and their dose bands are **external truth a
  pharmacist must supply.** No clinical numbers are invented in code. Blocks PR B.
- **D-T2 — Weight staleness (default 90 days).** A patient weight older than the
  staleness window is treated as stale for `per_kg` checks → `WEIGHT_GATE`.
  Default proposed: **90 days**; pending clinical confirmation.
- **D-T3 — Engine-error policy = advisory.** If the engine throws (`ENGINE_ERROR`),
  the gate is **advisory** (warn + allow), not block — we fail open rather than
  block all prescribing on an engine bug. Pending confirmation.

---

## 6. PR A scope confirmation

PR A ships **only** the schema above: two new tenant-scoped pharmacy models, the
structured `PrescriptionItem` dose fields, the `AISafetyAlert.source` idempotency
fix, reversible migrations, tests, and this plan. **No dose engine, no
enforcement, no clinical numbers.** Those are PR B and require pharmacist input.
