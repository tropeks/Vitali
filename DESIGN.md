# Vitali Design System

> **Clinical-clean SaaS** — built for Brazilian health clinic operators, doctors, and billing staff.
> Trust, precision, and clarity above all. Not playful. Not corporate. Professional.

---

## 1. Brand Identity

**Product:** Vitali — Plataforma Hospitalar SaaS (ERP + EMR + Faturamento)
**Context:** Brazilian clinics and hospitals. Users are doctors, nurses, billing specialists (faturistas), and clinic admins. They're working fast, often under pressure. The UI must communicate status instantly and never create doubt about what something does.

**Design principles:**
1. **Clarity over cleverness** — Every element should be immediately scannable. Labels are full words in Portuguese, never cryptic icons alone.
2. **Data density without clutter** — Medical UIs need a lot on screen. Use tight but breathable spacing. Tables over cards when comparing rows.
3. **Status is sacred** — Clinical status (alergias, guia status, encounter status) always uses the semantic color system. Never reuse red for decoration.
4. **Trust through consistency** — Same pattern for the same action everywhere. Buttons, modals, toasts — don't reinvent them per-page.

---

## 2. Color System

### Primary — Clinical Blue

| Token | Tailwind | Hex | Use |
|-------|----------|-----|-----|
| `brand-50` | `bg-brand-50` | `#eff6ff` | Button hover bg, input focus bg |
| `brand-100` | `bg-brand-100` | `#dbeafe` | Light badge bg, info callouts |
| `brand-500` | `text-brand-500` | `#3b82f6` | Accent text, chart lines, icon fill |
| `brand-600` | `bg-brand-600` | `#2563eb` | **Primary button**, active nav, sidebar highlight |
| `brand-700` | `bg-brand-700` | `#1d4ed8` | Button hover state |
| `brand-900` | `bg-brand-900` | `#1e3a5f` | Dark sidebar, deep emphasis text |

### Neutrals — Slate Scale

| Token | Tailwind | Use |
|-------|----------|-----|
| `slate-50` | `bg-slate-50` | Page background |
| `slate-100` | `bg-slate-100` | Hover states on white |
| `slate-200` | `border-slate-200` | Card borders, dividers |
| `slate-400` | `text-slate-400` | Placeholder, disabled, metadata |
| `slate-500` | `text-slate-500` | Secondary labels |
| `slate-700` | `text-slate-700` | Body text |
| `slate-800` | `text-slate-800` | Table cell primary text |
| `slate-900` | `text-slate-900` | Headings, sidebar background |

> **Rule:** Use `slate-*` for text/bg. Use `gray-*` only for inline-component borders (inputs, cards) to maintain Tailwind compatibility with shadcn defaults. Don't mix gray and slate at the same hierarchy level.

### Semantic Colors — Status System

These colors carry meaning across the entire app. Never use them decoratively.

| Semantic | Bg | Text | Border | Use |
|----------|-----|------|--------|-----|
| **Critical** | `bg-red-50` | `text-red-700` | `border-red-200` | Life-threatening allergy, denied guide, urgent alert |
| **Warning** | `bg-yellow-50` | `text-yellow-700` | `border-yellow-200` | Moderate allergy, controlled condition, appeal in progress |
| **Success** | `bg-green-50` | `text-green-700` | `border-green-200` | Paid guide, resolved status, active insurance card |
| **Info** | `bg-blue-50` | `text-blue-700` | `border-blue-200` | In-context edit forms, informational callouts |
| **Neutral** | `bg-gray-50` | `text-gray-600` | `border-gray-200` | Inactive/historical records |
| **Orange** | `bg-orange-50` | `text-orange-700` | `border-orange-200` | Severe (not life-threatening) allergy severity |

#### Status badge recipes

```tsx
// Guide status
const GUIDE_STATUS_STYLES: Record<string, string> = {
  draft:     'bg-gray-100 text-gray-600',
  pending:   'bg-yellow-100 text-yellow-700',
  submitted: 'bg-blue-100 text-blue-700',
  paid:      'bg-green-100 text-green-700',
  denied:    'bg-red-100 text-red-700',
  appeal:    'bg-orange-100 text-orange-700',
}

// Allergy severity
const SEVERITY_COLORS: Record<string, string> = {
  life_threatening: 'bg-red-100 text-red-800 border-red-200',
  severe:           'bg-orange-100 text-orange-800 border-orange-200',
  moderate:         'bg-yellow-100 text-yellow-800 border-yellow-200',
  mild:             'bg-green-100 text-green-800 border-green-200',
}
```

---

## 3. Typography

### Font Families

| Role | Font | Tailwind | Where |
|------|------|----------|-------|
| UI text | **Inter** | `font-sans` | All UI labels, buttons, body text |
| Code / IDs | **JetBrains Mono** | `font-mono` | Medical record numbers, ANS codes, card numbers, CID-10 codes |

Both loaded via `next/font/google` (or system fallback). Never use serif.

### Type Scale

| Role | Class | Size | Weight | Use |
|------|-------|------|--------|-----|
| Page title | `text-2xl font-bold text-slate-900` | 24px/700 | H1 of every page |
| Section title | `text-lg font-semibold text-slate-900` | 18px/600 | Card headers, section headings |
| Card header | `text-base font-semibold text-slate-900` | 16px/600 | Inside card headers |
| Body | `text-sm text-slate-700` | 14px/400 | Default body, table cells |
| Label | `text-xs font-medium text-gray-400 uppercase tracking-wide` | 12px/500 | Field labels in detail views |
| Caption | `text-xs text-gray-500` | 12px/400 | Metadata, timestamps, secondary info |
| Mono ID | `text-sm font-mono text-gray-600` | 14px mono | Medical record numbers, codes |

---

## 4. Spacing & Layout

### Grid

```
Page padding:     p-6 (24px) on desktop, p-4 on mobile
Content gap:      gap-6 (24px) between major sections
Card inner:       p-5 (20px)
Form field gap:   gap-3 (12px)
Tight list gap:   space-y-2 (8px)
```

### Breakpoints (Tailwind defaults)

| bp | px | Use |
|----|-----|-----|
| `sm` | 640 | 2-col grids start |
| `lg` | 1024 | Sidebar shows fixed, 3-col grids |
| `xl` | 1280 | 4-col KPI cards |

### Sidebar

- Width: `w-64` (256px)
- Background: `bg-slate-900`
- Active item: `bg-blue-600 text-white font-medium rounded-lg`
- Inactive item: `text-slate-400 hover:text-white hover:bg-white/5 rounded-lg`
- Logo mark: 8×8 `rounded-lg bg-blue-600`

### Page layout pattern

```
┌─ Topbar (h-14, white, border-b-slate-200) ────────────────────┐
│  [Menu mobile] [Tenant name] [Notifications] [User menu]       │
└───────────────────────────────────────────────────────────────┘
┌─ Page header ──────────────────────────────────────────────────┐
│  <h1> Page Title          [Primary Action Button]              │
│  <p class="text-slate-500 text-sm mt-1"> Subtitle              │
└───────────────────────────────────────────────────────────────┘
┌─ Content area (space-y-6) ─────────────────────────────────────┐
│  [Cards / Tables / Forms]                                       │
└───────────────────────────────────────────────────────────────┘
```

---

## 5. Components

### Cards

```tsx
// Standard card
<div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">

// Card with header + content
<div className="bg-white rounded-xl border border-gray-200 shadow-sm">
  <div className="px-5 py-4 border-b border-gray-100">
    <h2 className="text-base font-semibold text-slate-900">Title</h2>
  </div>
  <div className="p-5">...</div>
</div>
```

### Buttons

| Variant | Classes |
|---------|---------|
| **Primary** | `bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors` |
| **Secondary** | `border border-gray-200 bg-white hover:bg-gray-50 text-slate-700 text-sm font-medium px-4 py-2 rounded-lg` |
| **Ghost** | `text-blue-600 hover:underline text-sm font-medium` (link-style inline actions) |
| **Danger** | `text-red-600 hover:text-red-700 text-sm font-medium` (destructive inline, e.g. "Desativar") |
| **Disabled** | Add `disabled:opacity-50 disabled:cursor-not-allowed` to any button |
| **Small** | Replace `px-4 py-2 text-sm` with `px-3 py-1.5 text-xs` |

### Inputs & Form Controls

```tsx
// Text input
<input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm
                  focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none
                  placeholder:text-gray-400" />

// Select
<select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm
                   focus:ring-2 focus:ring-blue-500 outline-none bg-white" />

// Date input — same as text input
// Textarea — same classes, add resize-none min-h-[80px]

// Field label
<label className="block text-xs font-medium text-gray-700 mb-1">
  Field Name {required && <span className="text-red-500">*</span>}
</label>

// Error message
<p className="text-xs text-red-600 mt-1">Error message here</p>
```

### In-context forms (edit inline)

Used for inline add/edit within a list (e.g. ConveniosTab, PriceTableItems):

```tsx
<div className="border border-blue-200 bg-blue-50 rounded-xl p-4 space-y-3">
  <h3 className="text-sm font-semibold text-gray-800">Form title</h3>
  {/* fields */}
  <div className="flex gap-2 justify-end">
    <button className="text-xs text-gray-500 px-3 py-1.5">Cancelar</button>
    <button className="bg-blue-600 text-white text-xs px-4 py-1.5 rounded-lg font-medium">
      Salvar
    </button>
  </div>
</div>
```

### Tables

```tsx
<div className="overflow-x-auto">
  <table className="w-full text-sm">
    <thead>
      <tr className="border-b border-gray-100">
        <th className="text-left py-3 px-4 text-xs font-medium text-gray-500 uppercase tracking-wide">
          Column
        </th>
      </tr>
    </thead>
    <tbody className="divide-y divide-gray-50">
      <tr className="hover:bg-gray-50 transition-colors">
        <td className="py-3 px-4 text-slate-800">Cell</td>
      </tr>
    </tbody>
  </table>
</div>
```

### Status Badges

```tsx
// Pill badge
<span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
  Pago
</span>

// Dot + text (for less critical status)
<span className="flex items-center gap-1.5 text-xs text-gray-500">
  <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
  Ativo
</span>
```

### Tabs

```tsx
<div className="border-b border-gray-200">
  <nav className="flex gap-6">
    {tabs.map(tab => (
      <button
        key={tab.id}
        onClick={() => setActiveTab(tab.id)}
        className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
          activeTab === tab.id
            ? 'border-blue-600 text-blue-600'
            : 'border-transparent text-gray-500 hover:text-gray-700'
        }`}
      >
        {tab.label}
      </button>
    ))}
  </nav>
</div>
```

### Skeleton / Loading States

```tsx
// Pulse skeleton
<div className="h-8 bg-gray-100 rounded animate-pulse w-1/3" />

// KPI card skeleton
<div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm space-y-3 animate-pulse">
  <div className="h-4 bg-gray-200 rounded w-32" />
  <div className="h-9 bg-gray-200 rounded w-20" />
</div>
```

### Empty States

```tsx
// Full-page empty
<div className="text-center py-16">
  <p className="text-sm text-gray-400">Nenhum registro encontrado.</p>
  <button className="mt-3 text-sm text-blue-600 hover:underline font-medium">
    + Criar novo
  </button>
</div>

// Inline empty (inside a card list)
<p className="text-sm text-gray-400 text-center py-6">Nenhum item cadastrado.</p>
```

### Alert / Warning Banners

```tsx
// Life-threatening allergy (always shown in patient header when applicable)
<div className="px-4 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 font-medium">
  ⚠️ Alergia com risco de vida: Penicilina, Dipirona
</div>

// General info banner
<div className="px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700">
  Informação contextual aqui.
</div>
```

### Patient Avatar

```tsx
// Used in patient headers and list rows
<div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center
                text-blue-600 font-semibold text-lg">
  {patient.full_name[0]}
</div>

// Small variant (list rows)
<div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center
                text-blue-600 font-semibold text-sm">
  {patient.full_name[0]}
</div>
```

---

## 6. Icons

Library: **lucide-react** (tree-shaken, consistent stroke weight 1.5).

Standard sizes:
- Navigation icons: `size={18}`
- Inline / button icons: `size={16}`
- Large feature icons: `size={24}`

Key icon usage:
| Icon | Lucide name | Context |
|------|-------------|---------|
| Dashboard | `LayoutDashboard` | Nav |
| Patients | `Users` | Nav |
| Schedule | `Calendar` | Nav |
| Waiting room | `ClipboardList` | Nav |
| Encounters | `Stethoscope` | Nav |
| Medical record | `FileText` | Nav |
| Pharmacy | `Pill` | Nav |
| Billing | `Receipt` | Nav |
| AI | `Sparkles` | Nav |
| Settings | `Settings` | Nav |
| Logout | `LogOut` | User footer |
| Notification | `Bell` | Topbar |
| Back | ← (text character) | Page back button |
| Search | `Search` | Search inputs |
| Add | `+` (text) or `Plus` | Add buttons |

---

## 7. Motion

Keep it minimal. Medical UIs should not animate unnecessarily — it distracts.

| Pattern | Class | Notes |
|---------|-------|-------|
| Button hover | `transition-colors` | Color only, instant |
| Sidebar slide (mobile) | `transition-transform` | Hardware-accelerated |
| Skeleton | `animate-pulse` | Breathing skeleton for loading |
| Tab underline | `transition-colors` | Smooth tab switch |

No entrance animations. No `animate-bounce`. No `animate-spin` except genuine loading spinners.

---

## 8. Accessibility

- **Focus rings**: All interactive elements must show `focus:ring-2 focus:ring-blue-500`. Never remove `outline` without replacing it.
- **Color alone**: Status colors always accompany a text label (not icon-only). A badge with background + text satisfies this.
- **Contrast**: slate-700 on white = 7.4:1 ✓. blue-600 on white = 4.6:1 ✓ (meets AA for large text).
- **Labels**: All form inputs have `<label>` with explicit `htmlFor` or wrapping pattern.
- **Toasts**: Keep under 4 seconds. Include a close button for screen reader users.

---

## 9. Patterns by Module

### EMR — Patient Record

- Patient header: avatar + name + MRN mono + age + gender + blood type (red)
- Life-threatening allergy banner always visible when `severity === 'life_threatening'`
- Tabs for sections: Dados Pessoais, Alergias, Histórico Médico, Convênios, Timeline
- Detail rows: label (xs uppercase gray-400) + value (sm slate-900)

### Billing — TISS/TUSS

- Guide list: table with guide number (mono), patient name, provider, competency, total value, status badge + action links
- Guide status progression: `draft → pending → submitted → paid / denied → appeal`
- Glosa badge: red badge on denied guide with count
- Batch: card showing guide count + total value + status + close/export actions
- TUSS combobox: debounced 300ms, shows `code — description (group)`, outside-click dismiss

### Dashboard — Analytics

- KPI cards: 4-col grid, each with label (gray-500) + large value (colored) + subtitle
- Chart wrappers: white card with header, ResponsiveContainer
- Chart line colors: blue-500 (total), green-500 (completed), red-400 (cancelled)

### Encounters — SOAP

- Split layout or full-width on smaller screens
- SOAP section headers: S / O / A / P with colored left-border
- Prescription chips: inline removable tags
- Sign button: prominent primary, top-right, requires confirmation

---

## 10. Do / Don't

| Do | Don't |
|----|-------|
| Use `rounded-xl` for cards | Mix `rounded-lg` and `rounded-xl` for the same component type |
| Use `border border-gray-200` for card borders | Use `shadow-md` or `shadow-lg` — `shadow-sm` is the max |
| Use semantic red for clinical warnings | Use red for decorative/marketing elements |
| Use `font-mono` for all medical codes | Show ANS codes or CID-10 in regular font |
| Keep empty states friendly but brief | Show technical error messages to end users |
| Use `text-blue-600 hover:underline` for inline ghost actions | Create tertiary buttons with borders for inline actions |
| Show loading skeletons for anything >200ms | Show spinners for page-level loads (prefer skeleton) |
| Use `confirm()` for destructive inline actions (deactivate, delete) | Use modals for simple yes/no confirmations |

---

## 11. File Conventions

```
frontend/
├── components/
│   ├── layout/         # DashboardShell, Topbar, Sidebar
│   ├── ui/             # Shadcn primitives (Button, Input, Dialog, Toast)
│   ├── billing/        # TUSSCodeSearch, GuideForm, BatchCard
│   ├── emr/            # PatientCard, AllergyBadge, SOAPEditor
│   ├── appointments/   # AppointmentModal, CalendarView
│   └── shared/         # StatusBadge, LoadingSkeleton, EmptyState
└── app/(dashboard)/
    ├── dashboard/      # Analytics
    ├── patients/       # EMR patient list + detail
    ├── appointments/   # Scheduling
    ├── encounters/     # SOAP notes
    ├── waiting-room/   # Queue management
    └── billing/        # TISS guides, batches, glosas, price tables
```

Shared primitives to extract as usage grows:
- `<StatusBadge status="paid" />` — resolves to correct color + label
- `<LoadingSkeleton variant="card" | "table-row" />` — standard skeletons
- `<EmptyState message="..." action={...} />` — consistent empty state

---

*Last updated: 2026-03-30 | Version: 1.0.0*
