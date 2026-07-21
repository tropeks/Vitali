# Vitali Design System

> ⚠️ **SUPERSEDED (2026-07-21).** The flat visual language described below lost
> the A/B decision of 2026-07-19 — see the decision record at
> [`docs/design/design-ab-flat-vs-neumorphic.html`](docs/design/design-ab-flat-vs-neumorphic.html).
> The product's visual skin is now **Tasy Neumorphic**: canonical values and
> component recipes live in [`docs/FRONTEND_GUIDELINES.md`](docs/FRONTEND_GUIDELINES.md),
> the token layer lives in `frontend/tailwind.config.ts` (`neu.*` colors,
> `neu-*` shadows) + `frontend/app/globals.css` (`.neu-*` classes), and the
> rollout is documented in
> [`docs/plans/2026-07-21-neumorphic-structural-reskin.md`](docs/plans/2026-07-21-neumorphic-structural-reskin.md).
> The **structural** content below (semantic status maps via
> `lib/operational-ui`, shared primitives, density and information-hierarchy
> principles) remains valid; only the flat surface treatment is retired.

> **Clinical-clean SaaS** — built for Brazilian health clinic operators, doctors, and billing staff.
> Trust, precision, and clarity above all. Not playful. Not corporate. Professional.

> **v2.0 — Reconciled operational language.** This contract now describes the
> dense, flat, status-first language established by the UI reconciliation work
> (TISS workbench, pharmacy cockpit, patient command center, schedule/waiting
> room) and the shared primitives that enforce it. v1.0.0 documented an earlier
> `rounded-xl` / `gray-200` / `shadow-sm` card spec that no shipped screen
> followed; that spec is **retired**. When in doubt, the shared primitives in
> `components/shared` and the canonical maps in `lib/operational-ui` are the
> source of truth — this document explains them.

---

## 1. Brand Identity

**Product:** Vitali — Plataforma Hospitalar SaaS (ERP + EMR + Faturamento)
**Context:** Brazilian clinics and hospitals. Users are doctors, nurses, billing specialists (faturistas), pharmacists, and clinic admins. They work fast, often under pressure. The UI must communicate status instantly and never create doubt about what something does.

**Design principles:**
1. **Clarity over cleverness** — Every element is immediately scannable. Labels are full words in Portuguese, never cryptic icons alone.
2. **Data density without clutter** — Medical UIs need a lot on screen. Tight but breathable spacing. Tables over cards when comparing rows.
3. **Status is sacred** — Clinical and workflow status always resolves through the canonical maps in `lib/operational-ui`. Never inline a status colour at the call site. Never reuse red for decoration.
4. **Trust through consistency** — Same pattern for the same action everywhere. Buttons, modals, badges, KPI tiles, page shells — use the shared primitive, don't re-roll it per page.
5. **One source of truth** — A status label/colour, a page shell, a KPI tile, an empty state: each has exactly one implementation. Divergence is a bug.

### Enterprise/Tasy-grade UX contract

The benchmark is Tasy/Rede D'Or-style hospital operations: integrated, dense, status-first, fast to scan. Vitali must not feel like a generic SaaS dashboard with isolated modules.

- **Operational first screen:** Dashboards expose the immediate queue of work before secondary analytics: waiting patients, open encounters, schedule friction, billing/pharmacy blockers.
- **Integrated patient context:** Patient detail is the clinical command center — identity, MRN, risk flags, active conditions, coverage, contact, and direct actions into agenda, encounters, billing, pharmacy.
- **Tabbed clinical workspace:** Inside an encounter the user stays in one patient workspace with a persistent patient bar and tabs (summary, SOAP, CPOE, vitals, documents, billing). Clinical workspaces hide the global sidebar.
- **Workbench surfaces:** Guide creation and dispensação are dense operator workbenches (context strip → working grid → sticky closing panel with explicit readiness), not generic forms.
- **No ambiguous loading:** Skeletons or explicit retryable errors. A page never looks indefinitely blank or stuck.
- **Status text is mandatory:** Every semantic colour carries a visible Portuguese label. Icons and colours are supporting cues, never the only signal.

---

## 2. Page Shells — `<PageShell variant>`

**Hybrid by screen type.** There are exactly two page shells. Screens must not hand-roll the outer wrapper — import `PageShell` from `@/components/shared` and pick a variant.

| Variant | Use for | Renders |
|---|---|---|
| `workbench` | Focused form / order-entry flows (TISS guide, dispensação, pharmacy cockpit). Capped + centred so dense forms stay readable on ultrawide. | `min-h-full bg-slate-50` → `mx-auto max-w-[1500px] space-y-4` |
| `operational` | Queue / table-heavy dashboards (agenda, sala de espera, patient command center). Full-bleed to maximise dense-table real estate. | `space-y-5` (full width; the dashboard layout owns padding) |

```tsx
import { PageShell } from '@/components/shared'

export default function Page() {
  return <PageShell variant="workbench">{/* header, sections… */}</PageShell>
}
```

Loading and error early-returns use the **same** shell variant as the screen, so the page never changes width between states.

---

## 3. Color System

Screens use literal Tailwind `blue-*` / `slate-*` classes (the `brand-*` token in `tailwind.config.ts` exists but is **not** used by operational screens — do not introduce it here).

### Primary — Clinical Blue

| Token | Use |
|-------|-----|
| `blue-50` | Button hover bg, input focus bg, in-context form bg, selected row tint |
| `blue-100` | Light badge bg, info callouts |
| `blue-600` | **Primary button**, active nav, sidebar highlight, primary links |
| `blue-700` | Primary button hover, link hover text |
| `blue-900/950` | Deep emphasis numerals (tinted KPI value) |

### Neutrals — Slate Scale

| Token | Use |
|-------|-----|
| `slate-50` | Page background, hover on white, table header bg, mono lot/code tiles |
| `slate-100` | Hover states, dividers between rows |
| `slate-200` | **Card / input / table borders, dividers** |
| `slate-400` | Placeholder, disabled, decorative icons |
| `slate-500` | Secondary labels, KPI tile label, captions |
| `slate-700` | Body text, secondary buttons |
| `slate-900` | Headings, sidebar background |

> **Rule:** Use `slate-*` for text, bg, and borders across operational surfaces. (v1.0.0's "gray-200 for component borders" rule is retired — every reconciled screen standardised on `slate-200`.) Don't mix `gray-*` and `slate-*` at the same hierarchy level.

### Semantic Colors — carried by `OperationalTone`

Never used decoratively. Every status resolves to one of these tones via `lib/operational-ui`.

| Tone | Pill (`badgeClass`, 100-bg) | Soft chip (`TONE_CLASSES`, 50-bg) | Meaning |
|------|------------------------------|-----------------------------------|---------|
| `critical` | `bg-red-100 text-red-700 border-red-200` | `bg-red-50 text-red-700 border-red-200` | Life-threatening allergy, denied guide, no-show, expired stock |
| `attention` | `bg-yellow-100 text-yellow-800 border-yellow-200` | `bg-yellow-50 text-yellow-800 border-yellow-200` | Pending, waiting, partial, expiring/low stock, appeal |
| `success` | `bg-green-100 text-green-800 border-green-200` | `bg-green-50 text-green-800 border-green-200` | Paid, dispensed, in attendance, resolved |
| `info` | `bg-blue-100 text-blue-800 border-blue-200` | `bg-blue-50 text-blue-800 border-blue-200` | Submitted, **signed prescription (actionable)**, confirmed |
| `neutral` | `bg-slate-100 text-slate-600 border-slate-200` | `bg-white text-slate-700 border-slate-200` | Draft, scheduled, historical/inactive |
| *severe* | `bg-orange-100 text-orange-800 border-orange-200` | `bg-orange-50 text-orange-800 border-orange-200` | Severe (not life-threatening) allergy, appeal |

> **Resolved conflict:** a **signed** prescription is `info`/blue ("liberada, acionável"); green is reserved for **dispensed** ("concluída"). Previously pharmacy/dispensação rendered signed green while the patient command center rendered it blue — blue is now canonical everywhere.

---

## 4. Canonical Status System — `lib/operational-ui`

This module is the **single source of truth** for every workflow status. Screens must never declare a status→colour map inline.

| Export | Covers |
|---|---|
| `getAppointmentStatusMeta(status)` | Appointment lifecycle styling (badge class + row stripe + left border for tables) |
| `appointmentBadgeLabel(status, statusDisplay?)` | The appointment badge **label** — same canonical-wins rule as `resolveBadgeMeta` (canonical for a known status, server `statusDisplay` only for unknown). Every appointment badge (agenda, sala de espera, patient command center) renders through this, never `status_display \|\| meta.label` |
| `GUIDE_STATUS_META` | TISS guide: `draft → pending → submitted → paid / denied → appeal` |
| `PRESCRIPTION_STATUS_META` | `draft → signed → partially_dispensed → dispensed / cancelled` |
| `ENCOUNTER_STATUS_META` | `open / signed / cancelled` |
| `ALLERGY_SEVERITY_META` | Severity as a pill |
| `ALLERGY_SEVERITY_BLOCK` | Severity as a 50-bg tinted card block |
| `getStockStatusMeta(item)` | Derives expired / expiring (≤30d) / low-stock badge, or `null` |
| `TONE_CLASSES` | Soft tinted chip for operational *signals* (atraso, espera, WhatsApp) |
| `resolveBadgeMeta(map, status, fallbackLabel?)` | Resolver — **canonical label wins for a known status**; `fallbackLabel` (server `status_display`) only applies when the status is unknown to the map |

```tsx
import { GUIDE_STATUS_META, resolveBadgeMeta } from '@/lib/operational-ui'
import { StatusBadge } from '@/components/shared'

<StatusBadge meta={resolveBadgeMeta(GUIDE_STATUS_META, guide.status, guide.status_display)} />
```

---

## 5. Shared Primitives — `components/shared`

The patterns that previously drifted are now one component each. Use them; do not re-implement.

### `<StatusBadge meta label? className? />`
The one bordered status pill. `meta` comes from a canonical map (above). `label` overrides only for genuinely dynamic text — prefer the canonical label.
Markup: `inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold`.

### `<KpiTile label value hint? icon? tone? />`
Operational metric tile. **Value is `text-2xl font-semibold`** (canonical — the operational camp previously drifted to `font-bold`). Omit `tone` for neutral white; pass a tone for tinted triage strips. Flat (no shadow).

### `<SectionState title detail tone? action? />`
Inline empty / degraded / informational block. `tone`: `neutral | success | warning | critical`.

### `<ReadinessPanel blockers readyText title? />`
The "Prontidão" summary for workbench closing panels. No blockers → states it can proceed; otherwise lists every blocker explicitly.

### `<PageShell variant />`
See §2.

> The patient command center keeps two local helpers — `Field` (label/value pair in detail views) and a thin `statusBadge` adapter for *derived boolean* badges (cadastro ativo/inativo, condição ativa/controlada/resolvida). Domain workflow statuses there route through the canonical maps.

---

## 6. Typography

| Role | Class | Notes |
|------|-------|-------|
| Page title | `text-2xl font-semibold text-slate-900` in an **`<h1>`** | Always `<h1>` — one per page (v1's `font-bold` and the `<h2>` workbench titles are retired) |
| Section title | `text-base font-semibold text-slate-900` | Card/section headers (`<h2>`/`<h3>` by depth) |
| Body | `text-sm text-slate-700` | Default body, table cells |
| KPI value | `text-2xl font-semibold` | Via `<KpiTile>` |
| Label | `text-xs font-semibold uppercase tracking-wide text-slate-500` | Field/KPI labels |
| Caption | `text-xs text-slate-500` | Metadata, timestamps |
| Mono ID | `font-mono text-xs text-slate-500/700` | MRN, ANS, lot, TUSS, CID-10, guide numbers |

Fonts: **Inter** (`font-sans`) for UI, **JetBrains Mono** (`font-mono`) for all medical/record codes. Never serif.

---

## 7. Spacing, Cards & Layout

### Card — the canonical chrome

```tsx
// Standard card: flat by default
<section className="rounded-lg border border-slate-200 bg-white">
  <div className="border-b border-slate-100 px-4 py-3">
    <h2 className="text-base font-semibold text-slate-900">Title</h2>
  </div>
  <div className="p-4">…</div>
</section>
```

- Radius: **`rounded-lg`** (never `rounded-xl`).
- Border: **`border-slate-200`** (header divider `border-slate-100`).
- Elevation: **flat by default.** `shadow-sm` is allowed **only** for genuinely floating surfaces — sticky closing panels and modals. Static cards, KPI tiles, queues and the next-patient highlight are flat.
- Inner padding: `p-4` (`lg:p-5` only for the spacious patient header).

### Rhythm

```
workbench shell:  space-y-4   |   operational shell: space-y-5
KPI strip gap:    gap-3       |   content section gap: gap-4
Card header:      px-4 py-3   |   card body: p-4
```

### Breakpoints (Tailwind defaults)

`sm` 640 (2-col) · `lg` 1024 (sidebar fixed, desktop tables) · `xl` 1280 (4-col KPI / sticky workbench panel) · `2xl` 1536.

**Tables for comparison, cards for mobile.** Desktop record/queue lists are compact `<table>`s; below `lg`/`md` they collapse to dedicated record cards — never a squeezed desktop table.

---

## 8. Components (other)

- **Buttons:** Primary `bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg`; Secondary `border border-slate-200 bg-white hover:bg-slate-50 text-slate-700`; Ghost `text-blue-600 hover:underline`; Danger inline `text-red-600`. Add `disabled:opacity-50 disabled:cursor-not-allowed`.
- **Inputs:** `w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 placeholder:text-slate-400`. Labels `text-xs font-medium text-slate-700`, required marker `text-red-600 *`.
- **In-context forms:** `rounded-lg border border-blue-200 bg-blue-50 p-4` (inline add/edit, e.g. ConveniosTab).
- **Tabs:** underline style — active `border-blue-600 text-blue-700`, inactive `border-transparent text-slate-500 hover:text-slate-800`, `border-b-2`.
- **Skeletons:** `animate-pulse` blocks on `bg-slate-100`. Skeleton for page/section load, never an indefinite blank.
- **Modals:** centred over `bg-black/50`; the panel may use elevation (`shadow-2xl`) since it floats.

---

## 9. Icons

**lucide-react**, stroke weight default. Sizes: nav `18`, inline/KPI `14–16`, feature `24`. Status is never icon-only — always paired with text.

---

## 10. Motion

Minimal. `transition-colors` on hover; `transition-transform` for the mobile sidebar; `animate-pulse` for skeletons; `animate-spin` only for genuine refresh/loading spinners. No entrance animations, no bounce.

---

## 11. Accessibility

- One `<h1>` per page (the page title). Section headings nest by depth.
- All interactive elements show `focus:ring-2 focus:ring-blue-500`; never remove `outline` without replacing it.
- Status colour is always accompanied by a text label (the `StatusBadge` satisfies this).
- All form inputs have an associated `<label>`.
- Destructive inline actions use `confirm()`; toasts < 4s with a close affordance.

---

## 12. Do / Don't

| Do | Don't |
|----|-------|
| `<PageShell variant>` for every screen | Hand-roll `min-h-full`/`max-w`/`space-y` wrappers |
| Resolve status via `lib/operational-ui` maps | Inline a status→colour ternary at the call site |
| `<StatusBadge>` / `<KpiTile>` / `<SectionState>` / `<ReadinessPanel>` | Re-implement the pill / tile / empty / readiness pattern per page |
| `rounded-lg border border-slate-200`, flat | `rounded-xl`, `shadow-sm` on static cards, `gray-200` borders |
| `<h1>` `text-2xl font-semibold` page title | `<h2>` page titles, `font-bold` titles or KPI numbers |
| Canonical Portuguese status label | Let server `status_display` drive a known status |
| `font-mono` for every medical code | Plain font for ANS/CID-10/MRN/lot |

---

## 13. File Conventions

```
frontend/
├── lib/
│   └── operational-ui.ts      # canonical status maps + resolveBadgeMeta + TONE_CLASSES + formatters
├── components/
│   ├── shared/                # PageShell, StatusBadge, KpiTile, SectionState, ReadinessPanel (+ index barrel)
│   ├── layout/                # DashboardShell, Topbar, Sidebar
│   ├── billing/ emr/ appointments/ …  # feature components
└── app/(dashboard)/
    ├── billing/guides/new/    # TISS workbench  (PageShell workbench)
    ├── farmacia/ + dispense/  # pharmacy cockpit + dispensação workbench (workbench)
    ├── patients/[id]/         # patient command center (operational)
    ├── appointments/          # agenda operacional (operational)
    └── waiting-room/          # sala de espera (operational)
```

New operational status? Add it to the relevant map in `lib/operational-ui` (and its test) — never to a screen.

---

*Last updated: 2026-05-17 | Version: 2.0.0 — reconciled operational language*
