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

Status: started

Target:

- Patient detail becomes the operational command center: identity, MRN, alerts, coverage, timeline, encounters, billing, and direct actions.
- Patient list remains dense on desktop and card-based on mobile.

First slice:

- Reconcile `/patients/[id]` into a patient command center with persistent identity, MRN, active risk, coverage, next appointment, open encounters, prescriptions, billing guides, and direct actions.
- Add patient-scoped API filters for appointments and TISS guides so the page does not depend on global list scans.
- Add focused frontend tests for risk/coverage/billing context, direct encounter navigation, and degraded module states.
- Add backend tests for patient-scoped appointment and guide filtering.

### R3 - Scheduling And Waiting Room

Status: started

Target:

- Agenda and waiting room become one operational flow: schedule friction, arrivals, delayed patients, check-in/start-encounter actions, and queue state.
- Use real `arrived_at`/`started_at` timestamps for waiting-room signals and direct encounter start.

First slice:

- Reconcile `/appointments` into an operational schedule cockpit with today's queue, delay/friction signals, check-in/start/PIX actions, and the weekly grid as a secondary planning surface.
- Keep `/waiting-room` as the focused real-time queue companion with explicit navigation back to the schedule cockpit.
- Add focused frontend tests for queue rendering, dedicated check-in, direct encounter start, and schedule/waiting-room navigation.

### R4 - Pharmacy Cockpit

Status: started

Target:

- Dispensation becomes a pharmacy queue/workbench, not a narrow wizard.
- Stock, lot selection, expiry, controlled-substance status, and prescription context are visible together.
- Pharmacy root gets an operational landing surface instead of redirect-only behavior.

First slice:

- Reconcile `/farmacia` into a cockpit with prescription queue, controlled-substance workload, stock alerts, and recent dispensation audit context.
- Reconcile `/farmacia/dispense` into a dispensation workbench with patient search/prefill, signed/partially-dispensed prescription queue, FEFO lots, Portaria 344 blockers, and explicit readiness.
- Expose patient name/MRN in prescription API responses so pharmacy workflows do not depend on raw patient UUIDs.
- Add focused frontend tests for cockpit metrics, queue links, FEFO context, and controlled-substance blockers.

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
- 2026-05-07: Started R4 Pharmacy Cockpit on branch `codex/ui-reconciliation-pharmacy-cockpit`.
- 2026-05-07: Reconciled `/farmacia` and `/farmacia/dispense`; visual evidence captured at `output/playwright/ui-reconciliation/pharmacy-cockpit-desktop.png`, `output/playwright/ui-reconciliation/pharmacy-cockpit-mobile.png`, `output/playwright/ui-reconciliation/pharmacy-dispense-desktop.png`, and `output/playwright/ui-reconciliation/pharmacy-dispense-mobile.png`.
- 2026-05-07: Started R2 Patient Command Center on branch `codex/ui-reconciliation-patient-command-center`.
- 2026-05-07: Reconciled `/patients/[id]`; visual evidence captured at `output/playwright/ui-reconciliation/patient-command-center-desktop.png` and `output/playwright/ui-reconciliation/patient-command-center-mobile.png`.
- 2026-05-07: Started R3 Scheduling And Waiting Room on branch `codex/ui-reconciliation-schedule-waiting-room`.
- 2026-05-07: Reconciled `/appointments` and `/waiting-room`; visual evidence captured at `output/playwright/ui-reconciliation/schedule-operational-desktop.png`, `output/playwright/ui-reconciliation/schedule-operational-mobile.png`, `output/playwright/ui-reconciliation/waiting-room-operational-desktop.png`, and `output/playwright/ui-reconciliation/waiting-room-operational-mobile.png`.
- 2026-05-17: Cross-screen convergence sprint. The four reconciled blocks had drifted (two page-shell camps, `<h2>` vs `<h1>` titles, `font-bold` vs `font-semibold` KPIs, prescription `signed` rendered green in pharmacy/dispensação but blue in the patient command center, status colours re-declared inline per screen). Resolved by:
  - `lib/operational-ui.ts` extended into the single source of truth for status: `GUIDE/PRESCRIPTION/ENCOUNTER/ALLERGY/STOCK` metas + `TONE_CLASSES` + `resolveBadgeMeta` (canonical label wins for known status; `signed`→blue, `dispensed`→green resolves the conflict).
  - New shared primitives `components/shared/` — `PageShell` (two named shells: `workbench` capped/centred, `operational` full-bleed — the approved "hybrid by screen type"), `StatusBadge`, `KpiTile`, `SectionState`, `ReadinessPanel`.
  - All six screens (`/billing/guides/new`, `/farmacia`, `/farmacia/dispense`, `/patients/[id]`, `/appointments`, `/waiting-room`) refactored onto the primitives; `<h2>`→`<h1>` on the workbenches; KPI numbers unified to `font-semibold`; cards flattened (`shadow-sm` only on floating surfaces).
  - `DESIGN.md` promoted to **v2.0** — retires the unused v1.0.0 `rounded-xl`/`gray-200` card spec and documents the reconciled language, the two named shells, the canonical status system, and the shared primitives as the contract.
  - Verified: `tsc --noEmit` clean · `next lint` clean · 20/20 vitest (6 screen suites + `operational-ui`).
- 2026-05-17: Tasy-grade visual direction **approved**. Reference spec at `output/design/vitali-tasy.html` (six surfaces; gitignored local evidence, same convention as the playwright shots). Adds Philips-Tasy idioms on top of the v2.0 foundation — barra do paciente (context-scoped, slide+fade on context change), pasta tabs, grid toolbars, lupa lookup fields, semáforo status, bottom F-key status bar. Codifying these idioms into shared primitives + `DESIGN.md` is the scope of the next sprint (R5 onward), not this one.

## Status

R0–R4 reconciled and **converged** (single design system, verified green). R5 (Admin/AI/WhatsApp/HR) and the approved Tasy-idiom codification remain as the next sprint.
