# F-03 — Auto-TISS (procedure capture → priced draft guide)

Locked epic plan (engineering review). This document captures intent so PR2/PR3
can be implemented against a fixed contract.

## Goal

When a clinician captures procedures during a consultation and the encounter is
signed, Vitali automatically produces a **priced draft TISS guide** for insured
patients — eliminating manual re-entry by the billing team (faturistas).

## 3-PR sequence

### PR1 — `EncounterProcedure` model + nested API (this PR)
Clinical-capture foundation. Adds `apps.emr.EncounterProcedure` (per-tenant) and a
nested REST surface under `EncounterViewSet`:

- `GET/POST  /api/v1/encounters/{id}/procedures/`
- `PATCH/DELETE /api/v1/encounters/{id}/procedures/{proc_id}/`

Writes are allowed **only while `encounter.status == "open"`** (otherwise HTTP 409
`ENCOUNTER_NOT_OPEN`); reads are always allowed. Permissions mirror
`EncounterViewSet`: writes need `emr.write`, reads need `emr.read`. Capture is NOT
gated behind the billing module — clinical capture works even if billing is off.

`tuss_code` is an app-layer-protected FK to the shared/public `core.TUSSCode`. The
field uses `on_delete=DO_NOTHING` (NOT native `PROTECT`): for a tenant→public FK,
Django's deletion Collector runs in the public schema and a native `PROTECT` would
query `public.emr_encounterprocedure` (which doesn't exist) → `ProgrammingError` 500
before the signal can fire. Protection is instead provided by the cross-schema
`pre_delete` signal (`apps/core/signals.py:protect_tuss_code_deletion`), which
iterates tenant schemas and raises `ProtectedError` if a TUSS code is referenced by
an `EncounterProcedure`.

> **Follow-up (pre-existing, separate PR):** billing's `TISSGuideItem.tuss_code` and
> `PriceTableItem.tuss_code` still use native `PROTECT` and likely share the same
> latent cross-schema deletion crash. Not fixed in F-03 PR1 — flagged for a dedicated
> follow-up (apply the same `DO_NOTHING` + signal pattern there).

`unit_value` exists as a **cached UX hint only — NOT billing truth**. It is left
`null` in PR1. Pricing is resolved at guide-build time in PR2.

### PR2 — Cascade: build the priced draft guide at sign time
At encounter-sign, fan out from the captured procedures to a draft `TISSGuide` +
`TISSGuideItem`s, priced from the patient's insurance price table. Lives entirely in
`apps.billing.services`. Resolves each procedure's price at build time (price table
lookup), writes `TISSGuideItem.unit_value`/`total_value`, and may backfill the
`EncounterProcedure.unit_value` UX hint.

### PR3 — Frontend capture
UI for capturing procedures on the encounter screen (TUSS autocomplete, quantity,
performed-by), surfacing the resulting draft guide to faturistas.

## Product decisions accepted

1. **Empty-procedure insured encounter → create a consulta guide.** An insured
   encounter with no captured procedures still generates a `guide_type="consulta"`
   guide (the consultation itself is billable). It is not skipped.
2. **Unpriced item → R$0 + needs-pricing flag.** If a procedure's TUSS code has no
   entry in the applicable price table, the guide item is created at `R$0` and the
   guide is flagged as needing manual pricing (faturista review) rather than failing
   the whole sign.
3. **Immutable after sign.** Once the encounter is signed, its procedures and the
   generated guide are frozen at the EMR layer. Corrections happen through the
   billing workflow, not by mutating captured procedures.

## emr ↔ billing boundary rule

`apps.emr` MUST NOT import `apps.billing`. Procedure capture is purely clinical;
pricing is a billing concern. Pricing lives in `apps.billing.services` and is
resolved at guide-build time (PR2). The only cross-module link is the shared
`core.TUSSCode` (public schema), referenced by both sides via app-layer-PROTECT FKs
because PostgreSQL does not enforce cross-schema referential integrity.

## Idempotency design (PR2)

Sign-time guide generation must be safe under retries / double-submit:

- Wrap the cascade in `select_for_update()` on the `Encounter` row so concurrent
  sign requests serialize.
- Add an `auto_generated` boolean (or marker) to the generated `TISSGuide` plus a
  **partial unique index** keyed on `(encounter)` where `auto_generated = true`, so
  at most one auto-generated guide can exist per encounter. A retry that finds the
  existing auto-generated guide is a no-op.
