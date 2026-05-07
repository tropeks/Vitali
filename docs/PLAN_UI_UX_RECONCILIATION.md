# UI/UX Reconciliation Plan

Generated: 2026-05-07

## Goal

Bring every Vitali module to the same enterprise/Tasy-grade level now established in the clinical workspace and CPOE: integrated flows, dense operational surfaces, mandatory status text, fast scanning, and evidence-backed validation.

## Definition of Done

Each reconciled block must ship with:

- Desktop and mobile layouts that do not require horizontal guessing for core tasks.
- Status-first Portuguese labels for every workflow state.
- No primary workflow depending on raw UUIDs, hidden technical IDs, or returning to another page to continue.
- Loading, empty, degraded, and error states that are explicit and recoverable.
- Unit/component coverage for business-critical UI behavior.
- At least one E2E or Playwright visual evidence path for the critical workflow.
- Documentation update when the workflow contract changes.

## Workstreams

### R0 - Product Contract And Audit

Status: in progress

- Maintain this reconciliation plan as the execution ledger.
- Keep `DESIGN.md` as the UX contract.
- Track module-by-module gaps against the Tasy-grade standard.

### R1 - Billing/TISS Workbench

Status: started

Target:

- Guide creation must feel like a billing operator workbench, not a generic form.
- Encounter/patient/provider context is visible at all times.
- Procedure entry uses a dense grid with inline TUSS, AI suggestions, glosa risk, quantity, price, and blockers.
- The submit panel shows readiness, total, missing fields, and next action.

First slice:

- Reconcile `/billing/guides/new`.
- Add focused tests for required blockers, totals, and context rendering.
- Capture desktop/mobile screenshots after validation.

### R2 - Patient Command Center

Status: planned

Target:

- Patient detail becomes the operational command center: identity, MRN, alerts, coverage, timeline, encounters, billing, and direct actions.
- Patient list remains dense on desktop and card-based on mobile.

### R3 - Scheduling And Waiting Room

Status: planned

Target:

- Agenda and waiting room become one operational flow: schedule friction, arrivals, delayed patients, check-in/start-encounter actions, and queue state.
- Replace derived/demo wait metrics with real `arrived_at`/`started_at` once backend support lands.

### R4 - Pharmacy Cockpit

Status: planned

Target:

- Dispensation becomes a pharmacy queue/workbench, not a narrow wizard.
- Stock, lot selection, expiry, controlled-substance status, and prescription context are visible together.
- Pharmacy root gets an operational landing surface instead of redirect-only behavior.

### R5 - Admin, AI, WhatsApp, HR

Status: planned

Target:

- Settings pages use status-led operational panels.
- AI/DPA compliance blockers are explicit.
- WhatsApp connection and automation states are clear and auditable.
- HR onboarding/deactivation cascades show downstream effects.

## Execution Order

1. Billing/TISS guide creation.
2. Pharmacy dispensation and root cockpit.
3. Patient detail command center.
4. Agenda/waiting room.
5. AI/DPA/WhatsApp settings.
6. HR cascade visibility.

## Evidence Log

- 2026-05-07: Started R1 Billing/TISS Workbench on branch `codex/ui-reconciliation-billing-workbench`.
- 2026-05-07: Reconciled `/billing/guides/new` into a TISS workbench; visual evidence captured at `output/playwright/ui-reconciliation/billing-tiss-workbench-desktop.png` and `output/playwright/ui-reconciliation/billing-tiss-workbench-mobile.png`.
