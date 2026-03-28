<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260327-144344.md -->

# Vitali — Sprint 6 Plan: Prescriptions + Pharmacy

> **Branch:** master | **Date:** 2026-03-27 | **Status:** APPROVED — /autoplan complete (CEO + Eng + Design reviewed, gate passed)

---

## Context

**Project:** Vitali — Brazilian hospital SaaS (ERP+EMR+AI), multi-tenant (Django + Next.js + PostgreSQL schema-per-tenant)

**Completed sprints:**
- Sprint 1: Auth JWT, RBAC, audit log, frontend login + dashboard layout
- Sprint 2: Patient management, allergies, medical history, professional registry, schedule config
- Sprint 3: Scheduling, appointments, waiting room, calendar UI
- Sprint 4: Encounters, SOAP notes, vital signs, clinical documents
- Sprint 5: Analytics API, KPI dashboard, charts (jumped ahead; prescriptions deferred)

**What exists that this sprint depends on:**
- `apps/emr/models.py`: Patient, Professional, Encounter, SOAPNote, VitalSigns, ClinicalDocument
- `apps/pharmacy/`: empty stub (apps.py, migrations only)
- `apps/billing/`: empty stub
- Data model doc defines: Prescription, PrescriptionItem, Drug, Material, StockItem, StockMovement, Dispensation, Lot

**Sprint 6 Goal:** Close the clinical workflow loop by building prescriptions (the missing link between encounters and pharmacy) and the pharmacy module (drug catalog, inventory, dispensation). By end of sprint, a doctor can write a prescription, and a pharmacist can dispense it with stock auto-decremented.

---

## Scope

### S-015: Prescription Builder

**Goal:** Doctors create signed medication prescriptions linked to encounters.

**Prescription immutability — override `save()`:**
The plan says PATCH is rejected after signing, but an API guard alone is insufficient. Add a `save()` override on `Prescription` that raises `PermissionDenied` if `self.pk` already exists and `self.signed_at is not None`, unless the `update_fields` kwarg is limited to `['signature_hash', 'signed_at', 'signed_by']`. Mirror the `AuditLog.save()` guard in `apps/core/models.py` (lines 301–304). Do NOT rely solely on the viewset-level check.

**Backend — `apps/emr/models.py` additions:**
```
Prescription:
  - id: UUID (PK)
  - encounter: FK → Encounter (NOT NULL)
  - prescriber: FK → Professional (NOT NULL)
  - patient: FK → Patient (NOT NULL)
  - type: ENUM('medication','exam','procedure','diet','nursing') DEFAULT 'medication'
  - status: ENUM('draft','active','dispensed','cancelled','expired') DEFAULT 'draft'
  - valid_until: DATE (nullable)
  - notes: TEXT
  - signed: BOOLEAN DEFAULT false
  - signed_at: TIMESTAMP (nullable)
  - signed_by: FK → User (nullable)
  - created_at, updated_at

PrescriptionItem:
  - id: UUID (PK)
  - prescription: FK → Prescription (NOT NULL)
  - drug: FK → pharmacy.Drug (nullable — for catalog-linked items)
  - description: TEXT NOT NULL (free text fallback)
  - dosage: VARCHAR(100) e.g. "500mg"
  - route: VARCHAR(50) e.g. "oral", "IV", "IM", "SC"
  - frequency: VARCHAR(100) e.g. "8/8h", "1x/dia", "SOS"
  - duration: VARCHAR(50) e.g. "7 dias", "uso contínuo"
  - quantity: DECIMAL(10,2) nullable
  - unit: VARCHAR(20) nullable
  - instructions: TEXT (e.g. "tomar em jejum")
  - sort_order: INTEGER DEFAULT 0
  - created_at
```

**Backend API (`apps/emr/`):**
- `POST /api/v1/emr/prescriptions/` — create prescription (requires open encounter)
- `GET /api/v1/emr/prescriptions/` — list (filter by patient, encounter, status)
- `GET /api/v1/emr/prescriptions/{id}/` — retrieve
- `PATCH /api/v1/emr/prescriptions/{id}/` — update (only if not signed)
- `POST /api/v1/emr/prescriptions/{id}/sign/` — sign (sets signed=true, status=active, immutable after)
- `POST /api/v1/emr/prescriptions/{id}/cancel/` — cancel (only if not dispensed)
- `GET /api/v1/emr/prescriptions/{id}/print/` — return print-ready JSON for PDF generation
- `POST/DELETE/PATCH /api/v1/emr/prescriptions/{id}/items/` — item management (CRUD)
- `GET /api/v1/emr/drugs/search/?q=...` — drug search (delegates to pharmacy.Drug, fuzzy via pg_trgm)

**Signing rules:**
- Signing is irreversible — content hash computed on sign (SHA-256 of serialized items)
- Signed prescriptions reject PATCH on items (400 with error message)
- Prescriber must be a Professional linked to the request user

**Audit events — required `log_audit()` calls for Sprint 6 (reuse `log_audit()` from views.py:27):**
- `prescription_create` → `new_data: {patient, encounter, prescriber, type}`
- `prescription_sign` → `new_data: {content_hash, signed_by, item_count, prescriber_crm}` — CRM number is required for CFM compliance audit trail
- `prescription_cancel` → `new_data: {reason, cancelled_by, previous_status}`
- `drug_create` → `new_data: {name, anvisa_code, is_controlled}`
- `drug_update` (deactivation) → `old_data: {is_active: true}, new_data: {is_active: false}`

**Frontend (`/encounters/[id]` — Prescrição tab):**
- Prescription builder embedded in encounter detail page (new tab alongside Notas SOAP, Sinais Vitais)
- **Tab open behavior:** auto-create draft prescription on first open (consistent with SOAPEditor pattern — no extra click required)
- **Autosave draft:** debounced 800ms (same pattern as SOAPEditor — reuse `readOnly` prop)
- Drug search autocomplete: type 2+ chars → `/api/v1/emr/drugs/search/` → dropdown
  - **Loading state:** show spinner in input after 300ms debounce while fetch in-flight ("Buscando...")
  - **Keyboard nav:** arrow keys cycle through results; Enter selects; Escape closes — standard combobox accessibility
  - **Network error state:** retry button inline ("Não foi possível buscar — tentar novamente")
  - Controlled substance: 🔴 badge inline in results + in item list
  - Empty result: "Não encontrado — usar descrição livre" option
- Add item form: drug (catalog optional), description, dosage, route, frequency, duration, quantity, instructions
- Drag-to-reorder + up/down arrow buttons (tablet fallback)
- **"Assinar Prescrição" button:** confirmation modal ("ação irreversível") → disabled+spinner during signing → on success: read-only + status="Ativa" → on error: toast + re-enable
- Print view (WeasyPrint server-side PDF — decision #17):
  - `GET /api/v1/emr/prescriptions/{id}/print/` returns a PDF response (`Content-Type: application/pdf`)
  - Frontend: "Imprimir" button → spinner ("Gerando PDF...") → browser opens PDF in new tab on success → toast error on failure ("Erro ao gerar prescrição — tente novamente")
  - WeasyPrint renders a Django HTML template with required fields:
    - Clinic: nome, CNPJ, endereço, telefone
    - Prescriber: nome, CRM nº + UF, especialidade
    - Patient: nome, CPF, data de nascimento
    - Date: cidade, data de emissão
    - Items: medicamento, dose, via, frequência, duração, instruções
    - Signature line
  - Dockerfile dependency: `libpango1.0-0 libcairo2 libgdk-pixbuf2.0-0`
- Status badge: draft=cinza / active=verde / dispensed=azul / cancelled=vermelho

**Route note:** Frontend lives at `/encounters/[id]` (tab), not a separate `/prescriptions/` route, matching DashboardShell nav convention.

**Shared API client:** `PrescriptionBuilder` and `PatientTimeline` must import from `frontend/lib/api.ts` (new, thin wrapper — `apiFetch`/`apiPost`/`apiPatch` with shared auth header logic). Do NOT inline fetch functions per-component; `encounters/[id]/page.tsx` already has 3 duplicate inline fetch helpers and `SOAPEditor.tsx` has a 4th — do not extend this pattern to Sprint 6 components.

**CPF nullable migration:** `Patient.cpf` is currently `EncryptedCharField(max_length=14)` with no `null=True`. To support foreign nationals (accepted Gap 4 fix), add a standalone migration in `apps/emr/` adding `null=True, blank=True` to `Patient.cpf`. This migration must run **before** the prescription FK migration (since `Prescription` references `Patient`).

---

### S-016: Patient Timeline

**Goal:** Unified chronological view of all patient clinical events.

**Timeline stub conflict:** `PatientViewSet` in `views.py` (lines 83–100) already has a partial timeline action that aggregates encounters only (hardcoded limit 20). S-016 must **extend this action**, not create a new endpoint. Remove the hardcoded stub logic and replace with the full aggregation. Otherwise two code paths diverge.

**Backend API (`apps/emr/`):**
- `GET /api/v1/emr/patients/{id}/timeline/` — aggregates across models:
  - Encounters (with status, diagnoses)
  - Prescriptions (with item count, status)
  - SOAPNotes (type, signed status)
  - VitalSigns (last recorded set)
  - Dispensations (from pharmacy — when built)
  - Appointments (status)
- Returns sorted list with `type`, `date`, `summary`, `id` per event
- Filter params: `?type=encounter,prescription`, `?from=YYYY-MM-DD`, `?to=YYYY-MM-DD`

**Frontend (`/patients/[id]/timeline`):**
- Timeline component on patient detail page (new tab)
- **Loading state:** skeleton rows while fetching (3 rows, same height as real events)
- **Empty state:** "Nenhum evento clínico registrado" with the patient's name — not a blank list
- **Error state:** "Não foi possível carregar o histórico" + retry button (same pattern as timeline API fetch)
- Vertical timeline with event type icons (lucide-react):
  - `encounter` → `Stethoscope`
  - `prescription` → `Pill`
  - `soapnote` → `FileText`
  - `vitalsigns` → `Activity`
  - `appointment` → `Calendar`
  - `dispensation` → `Package` (Sprint 7)
- Clickable items navigate to the event detail
- Date range filter: use shadcn `DateRangePicker` (not native `<input type="date">`)
- Event type filter chips

---

### S-026: Drug & Material Catalog

**Goal:** Central catalog of drugs and materials used across prescriptions and stock.

**Backend — `apps/pharmacy/models.py`:**
```
Drug:
  - id: UUID (PK)
  - name: VARCHAR(255) NOT NULL (nome comercial)
  - generic_name: VARCHAR(255) nullable (princípio ativo)
  - manufacturer: VARCHAR(255)
  - presentation: VARCHAR(255) (e.g. "comprimido 500mg", "frasco 100ml/500mg")
  - barcode: VARCHAR(50)
  - anvisa_code: VARCHAR(20)
  - is_controlled: BOOLEAN DEFAULT false (Portaria 344 controlled)
  - control_type: VARCHAR(10) nullable (e.g. "C1", "A1", "B1")
  - requires_prescription: BOOLEAN DEFAULT true
  - is_active: BOOLEAN DEFAULT true
  - created_at, updated_at
  INDEX: pg_trgm on (name), (generic_name); unique (barcode) where not null

Material:
  - id: UUID (PK)
  - name: VARCHAR(255) NOT NULL
  - description: TEXT
  - category: VARCHAR(100) (e.g. "surgical", "disposable", "lab", "cleaning")
  - barcode: VARCHAR(50)
  - unit: VARCHAR(20) NOT NULL (e.g. "un", "cx", "pct", "ml", "kg")
  - tuss_code: VARCHAR(20) nullable
  - is_active: BOOLEAN DEFAULT true
  - created_at, updated_at
```

**pg_trgm extension:** Add to an early pharmacy migration:
```python
migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS pg_trgm", reverse_sql="SELECT 1")
```
Without this, `django test` creates a fresh DB with no extension and all drug search tests fail on CI.

**Drug search security:** Require `pharmacy.read` permission on the search endpoint. Add DRF `ScopedRateThrottle` at `'drug_search': '60/min'` to prevent BNAFAR dataset scraping. Without a permission check, any authenticated user (including `recepcionista`) can enumerate the full catalog.

**BNAFAR encoding note:** ANVISA flat files use pipe-delimited format with potential Windows-1252 encoding (older dumps), duplicate EAN codes, and irregular NULL representations (`"N/A"`, empty string, literal `"null"`). The `seed_bnafar` command must: detect encoding, normalize NULLs, deduplicate on `anvisa_code`, and run inside `set_tenant()` for each tenant. Budget 4–8h for data cleaning, not 1h.

**BNAFAR progress logging:** `seed_bnafar` must emit progress via `self.stdout.write()` every 1,000 rows (running count) and a final summary line: `"Seeded {n} drugs for tenant {schema_name} in {elapsed:.1f}s"`. An 80k-row silent import is undebuggable on first deployment.

**Backend API (`apps/pharmacy/`):**
- `GET/POST /api/v1/pharmacy/drugs/` — list/create
- `GET/PATCH/DELETE /api/v1/pharmacy/drugs/{id}/` — retrieve/update/deactivate
- `GET /api/v1/pharmacy/drugs/search/?q=...` — fuzzy search via pg_trgm (name + generic_name)
- `GET/POST /api/v1/pharmacy/materials/` — list/create
- `GET/PATCH /api/v1/pharmacy/materials/{id}/` — retrieve/update

**Frontend (`/pharmacy/catalog`):**
- Drug catalog table: columns = name, generic, manufacturer, presentation, controlled flag, active status
- Create/edit drug form with all fields
- Controlled substance toggle shows control_type selector
- Search bar with instant filtering
- Material catalog tab (same layout)

---

### S-027: Stock Management

**Goal:** Track inventory levels with lot/expiry tracking and alerts.

**Backend — `apps/pharmacy/models.py` additions:**
```
Lot:
  - id: UUID (PK)
  - drug: FK → Drug (nullable)
  - material: FK → Material (nullable)
  - lot_number: VARCHAR(100) NOT NULL
  - expiry_date: DATE NOT NULL
  - initial_quantity: DECIMAL(10,2) NOT NULL
  - current_quantity: DECIMAL(10,2) NOT NULL
  - created_at

StockItem:
  - id: UUID (PK)
  - item_type: ENUM('drug','material') NOT NULL
  - drug: FK → Drug (nullable)
  - material: FK → Material (nullable)
  - lot: FK → Lot NOT NULL
  - location: VARCHAR(100) nullable (e.g. "Almoxarifado A", "Farmácia Central")
  - min_stock: DECIMAL(10,2) DEFAULT 0
  - max_stock: DECIMAL(10,2) nullable
  - created_at

StockMovement:
  - id: UUID (PK)
  - stock_item: FK → StockItem NOT NULL
  - type: ENUM('entry','exit','adjustment','loss','transfer','dispensation') NOT NULL
  - quantity: DECIMAL(10,2) NOT NULL (positive = addition, negative = reduction)
  - quantity_before: DECIMAL(10,2) NOT NULL (snapshot for audit)
  - quantity_after: DECIMAL(10,2) NOT NULL (snapshot)
  - reason: TEXT nullable
  - reference_id: UUID nullable (FK to dispensation or PO)
  - performed_by: FK → User NOT NULL
  - performed_at: TIMESTAMP DEFAULT NOW()
```

**Backend API:**
- `GET /api/v1/pharmacy/stock/` — list current stock levels (aggregate by drug/material + lot)
- `POST /api/v1/pharmacy/stock/entry/` — add stock (creates Lot + StockItem + StockMovement 'entry')
- `POST /api/v1/pharmacy/stock/adjustment/` — manual adjustment with reason
- `GET /api/v1/pharmacy/stock/movements/` — movement history (filter by drug, date range)
- `GET /api/v1/pharmacy/stock/alerts/` — items below min_stock + items expiring in 30/60/90 days

**Celery tasks:**
- `check_expiry_alerts` — daily at 8am: query lots where expiry_date < now + 90d, send alert (Django signal or notification model)
- `check_min_stock_alerts` — daily at 8am: query stock_items where current_quantity < min_stock

**Frontend (`/pharmacy/stock`):**
- Stock dashboard: table with drug/material, lot, expiry, quantity, location, min/max
- Color coding: red = below min, yellow = expiring <30d, orange = expiring <60d
- "Add Stock Entry" modal (select drug, lot number, expiry, quantity, location)
- "Adjust Stock" modal with reason field
- Movement history tab (paginated table)
- Alerts panel (summary cards: below min, expiring soon)

---

### S-028: Dispensation

**Goal:** Pharmacist dispenses medication from a signed prescription with stock auto-decrement.

**Backend — `apps/pharmacy/models.py` additions:**
```
Dispensation:
  - id: UUID (PK)
  - prescription: FK → emr.Prescription NOT NULL
  - prescription_item: FK → emr.PrescriptionItem NOT NULL
  - stock_item: FK → StockItem NOT NULL
  - lot: FK → Lot NOT NULL
  - quantity_dispensed: DECIMAL(10,2) NOT NULL
  - dispensed_by: FK → User NOT NULL
  - dispensed_at: TIMESTAMP DEFAULT NOW()
  - notes: TEXT nullable
```

**Backend API:**
- `POST /api/v1/pharmacy/dispensations/` — dispense item:
  1. Validate prescription is signed and active
  2. Validate drug matches prescription item
  3. Select lot using FEFO (First Expiry First Out)
  4. Check stock sufficiency
  5. Decrement StockItem.lot.current_quantity
  6. Create StockMovement (type='dispensation', reference=dispensation.id)
  7. Create Dispensation record
  8. Update PrescriptionItem (mark as dispensed)
  9. If all items dispensed → update Prescription.status = 'dispensed'
  - Controlled substance: require user has `pharmacy.dispense_controlled` permission
- `GET /api/v1/pharmacy/dispensations/` — list (filter by prescription, patient, date)
- `GET /api/v1/pharmacy/dispensations/{id}/` — detail

**FEFO lot selection logic:**
```python
# Always select the lot expiring soonest with sufficient quantity
def select_fefo_lot(drug_id, quantity_needed):
    lots = StockItem.objects.filter(
        drug_id=drug_id,
        lot__current_quantity__gte=quantity_needed,
        lot__expiry_date__gt=today
    ).order_by('lot__expiry_date').select_related('lot')
    return lots.first()
```

**Frontend (`/pharmacy/dispensation`):**
- Scan/search prescription by patient name or prescription ID
- Show prescription items with status (pending dispensation)
- For each item: shows recommended lot (FEFO), quantity, expiry date
- "Dispense" button per item
- Controlled substance items show warning badge + require pharmacist confirmation
- "Dispense All" bulk action for non-controlled items
- Receipt view after dispensation (printable)

---

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Prescription ↔ Drug link | Nullable FK to pharmacy.Drug | Allow free-text prescriptions (not all drugs in catalog yet); FK enforces integrity when catalog item exists |
| Signing mechanism | SHA-256 hash of serialized content | Simple, auditable, compliant with CFM 1.821/2007 intent without full ICP-Brasil PKI (Phase 2) |
| FEFO implementation | Python-level selection (not DB trigger) | Readable, testable, and easy to override for special cases |
| Stock decrement atomicity | `select_for_update()` on StockItem row | Prevents race conditions on concurrent dispensations |
| Dispensation permission | `pharmacy.dispense_controlled` RBAC permission | Pharmacist role already has this; receptionist/nurse do not |
| Drug search in prescriptions | Delegates to pharmacy.Drug search endpoint | Single source of truth for drug catalog |
| PDF generation | WeasyPrint (server-side) | Reliable PDF output, archivable — browser print varies too much across devices for legal prescriptions. Add `libpango1.0-0 libcairo2 libgdk-pixbuf2.0-0` to Dockerfile. |

---

## Not In Scope (Sprint 6)

- **S-027 Stock management** — DEFERRED to Sprint 7. Validate in-house pharmacy prevalence in target segment before building.
- **S-028 Dispensation** — DEFERRED to Sprint 7. Depends on S-027.
- Purchase orders (S-029) — deferred to Sprint 7 alongside Billing
- TUSS codes on prescription items — deferred to Sprint 9 (AI layer)
- Controlled substance special registry (Portaria 344 full compliance) — MVP: RBAC gate only; SNGPC integration is Phase 2
- Drug interaction checking — Phase 2 (AI Clinical Safety Net)
- ICP-Brasil digital signature — Phase 2 (SHA-256 hash is MVP approximation)
- Barcode scanning hardware integration — Phase 2

## MVP Compliance Notice

**Electronic Prescriptions:** Vitali prescriptions use SHA-256 content hashing. This is an internal record system. Electronic prescriptions do NOT have the same legal standing as paper prescriptions until ICP-Brasil digital certificates are integrated (Phase 2). Clinics must be informed of this limitation.

**Controlled Substances:** Vitali gates controlled substance dispensation via RBAC permission. This does NOT replace SNGPC reporting (ANVISA Portaria 344). Clinics are responsible for their own SNGPC compliance. Phase 2 will add SNGPC report generation.

**BNAFAR Drug Seeding:** The drug catalog will be pre-seeded from ANVISA's public BNAFAR database on initial setup, providing a usable drug list from day 1.

---

## Acceptance Criteria

### End-to-end flow that must work (Sprint 6):
1. Doctor opens encounter → goes to Prescriptions tab → adds drug items (with catalog search) → signs prescription
2. Signed prescription appears as "Active" on patient profile
3. Patient timeline shows the prescription event
4. ~~Pharmacist opens Dispensation page → searches prescription → sees items → clicks Dispense → stock decremented → receipt shown~~ **DEFERRED — Sprint 7 (S-027/S-028)**
5. ~~Prescription status updates to "Dispensed"~~ **DEFERRED — Sprint 7 (S-027/S-028)**

### Key invariants:
- Signed prescriptions cannot be edited (API returns 400)
- Dispensation fails if no stock available (API returns 409 with clear message)
- Controlled substance dispensation blocked without `pharmacy.dispense_controlled` permission (403)
- Stock movements are immutable audit log (no update/delete on StockMovement)
- FEFO lot selection always picks earliest expiry

---

## Story Points

| Story | Points | Notes |
|-------|--------|-------|
| S-015 Prescription builder | 13 | Backend models + API + signing + frontend UI |
| S-016 Patient timeline | 5 | API aggregation + frontend component |
| S-026 Drug/material catalog | 5 | Models + CRUD API + search + BNAFAR seed script |
| ~~S-027 Stock management~~ | ~~8~~ | **DEFERRED to Sprint 7** — validate in-house pharmacy segment first |
| ~~S-028 Dispensation~~ | ~~8~~ | **DEFERRED to Sprint 7** — depends on S-027 |
| **Total** | **23** | ~2 weeks solo dev + AI |

---

## Architecture Diagram

```
SPRINT 6 — COMPONENT DEPENDENCY GRAPH

apps/core/
  ├── AuditLog (extend: prescription events)
  ├── User, Role, Permission (reuse)
  └── SignableMixin (NEW — extract from ClinicalDocument.sign() emr/models.py:344, share with Prescription)
        ↓
apps/emr/
  ├── Patient, Professional, Encounter (existing)
  ├── SOAPNote (uses SignableMixin — refactor)
  ├── Prescription (NEW — uses SignableMixin)
  │     └── ForeignKey → Encounter (NOT NULL)
  │     └── ForeignKey → Professional (NOT NULL, prescriber)
  ├── PrescriptionItem (NEW)
  │     └── ForeignKey → Prescription (NOT NULL)
  │     └── ForeignKey → pharmacy.Drug (NULL — free-text fallback)
  └── Timeline aggregation view (NEW — queries across 5 models)
        ↓
apps/pharmacy/
  ├── Drug (NEW — name, generic_name, anvisa_code, is_controlled, ...)
  ├── Material (NEW)
  └── management/commands/seed_bnafar.py (NEW — bulk_create from CSV)

frontend/(dashboard)/
  ├── encounters/[id]/page.tsx — ADD Prescrição tab
  │     └── PrescriptionBuilder component (NEW)
  │           └── DrugSearchInput component (NEW)
  ├── patients/[id]/page.tsx — ADD Timeline tab
  │     └── PatientTimeline component (NEW)
  └── farmacia/
        └── catalog/page.tsx (NEW) — Drug + Material tables

API Routes:
  GET/POST /api/v1/pharmacy/drugs/          — Drug CRUD
  GET      /api/v1/pharmacy/drugs/search/   — Fuzzy search (shared by prescribing + catalog)
  GET/POST /api/v1/pharmacy/materials/      — Material CRUD
  POST     /api/v1/emr/prescriptions/       — Create
  GET/PATCH /api/v1/emr/prescriptions/{id}/ — Read/update (draft only)
  POST     /api/v1/emr/prescriptions/{id}/sign/    — Sign
  POST     /api/v1/emr/prescriptions/{id}/cancel/  — Cancel
  GET      /api/v1/emr/prescriptions/{id}/print/   — Print JSON
  GET      /api/v1/emr/patients/{id}/timeline/      — Aggregated timeline

Migration order (enforced via dependencies=[]):
  pharmacy: 0001_initial (Drug, Material)
       ↓
  emr: 00XX_add_prescription (Prescription, PrescriptionItem with FK → pharmacy.Drug)
```

## Failure Modes Registry

| Failure | Severity | Plan coverage | Gap/Fix |
|---|---|---|---|
| Edit signed prescription via API | Critical | API rejects PATCH → 400 | ✓ Covered |
| Double-click sign → duplicate sign requests | High | Frontend: button disabled+spinner | ✓ Covered |
| Concurrent prescription item creates during sign | Medium | select_for_update() not on Prescription during sign | ⚠ Add: wrap sign operation in select_for_update() |
| Drug search returns hallucinated codes | N/A | Drugs from catalog only; AI TUSS is Sprint 9 | ✓ Not applicable yet |
| BNAFAR import creates duplicates on re-run | High | bulk_create(update_conflicts=True) on anvisa_code | ✓ Covered by decision #12 |
| Timeline query slow (N+1) | Medium | prefetch_related + cursor pagination | ✓ Covered |
| Expired prescription dispensed (Sprint 7) | High | valid_until check deferred | ⚠ Note for Sprint 7 |
| Migration order wrong (FK before table) | Critical | Explicit migration dependency declared | ✓ Covered by decision #13 |
| Print template renders incorrectly on mobile | Medium | @media print CSS + server-rendered JSON | ✓ Covered |
| Tenant isolation: drug catalog shared across tenants | High | Drug catalog is per-tenant (django-tenants schema routing) | ✓ By architecture |

| pg_trgm extension absent in test DB | Critical | Drug search + BNAFAR tests | Add `RunSQL("CREATE EXTENSION IF NOT EXISTS pg_trgm")` to pharmacy migration |
| Drug search scraping / wrong permission | High | `pharmacy.read` permission + throttle | Add `ScopedRateThrottle` 60/min + require `pharmacy.read` on search endpoint |
| Timeline stub conflict in PatientViewSet | Medium | Existing partial stub (encounters-only, limit 20) | S-016 extends the existing action — do not add a second endpoint |
| BNAFAR encoding/nulls in file | High | Encoding complexity (Windows-1252, irregular NULLs) | ⚠ Budget 4–8h; handle encoding detection and NULL normalization |
| Prescription model-level mutability after sign | Critical | API guard alone insufficient | Add `save()` override on Prescription model mirroring AuditLog guard |

| SignableMixin from wrong source | Medium | Developer reads Decision #10 "SOAPNote" as source, looks for signing logic in SOAPNote — finds nothing | ✓ Corrected: source is ClinicalDocument.sign() (emr/models.py:344) |
| API fetch duplication in new components | Medium | PrescriptionBuilder/Timeline inline their own apiFetch — breaks consistently when auth changes | ✓ Use shared frontend/lib/api.ts for all Sprint 6 components |
| CPF nullable migration ordering | High | Accepted Gap 4 fix (CPF nullable) requires explicit migration before prescription FK migration | ✓ Add standalone emr migration: null=True, blank=True on Patient.cpf, runs before prescription migration |

**Critical gap: wrap sign operation in select_for_update()** — Auto-deciding to add this. [Principle 1]

## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Mode: SELECTIVE EXPANSION | P6 (bias to action) | Hold scope + surface expansions as individual choices | SCOPE_EXPANSION (too early for MVP) |
| 2 | CEO | Drug catalog location: apps/pharmacy/ | P5 (explicit) | Matches architecture doc module boundaries; cross-app FK is standard Django | apps/emr/ (breaks module separation) |
| 3 | CEO | Signing: SHA-256 hash (MVP) | P3 (pragmatic) | ICP-Brasil PKI is months of work; MVP approximation acceptable with documented limitations | ICP-Brasil Sprint 6 (ocean not lake) |
| 4 | CEO | FEFO: Python-level selection | P5 (explicit) | Readable, testable; select_for_update() handles concurrency; DB trigger is over-engineered at MVP scale | DB trigger (accidental complexity) |
| 5 | CEO | **Defer S-027+S-028 to Sprint 7** | User decision (premise gate) | In-house pharmacy prevalence in target segment unvalidated; avoid 16pts of potentially unused work | Build all now (unvalidated assumption) |
| 6 | CEO | Drug catalog: seed from BNAFAR at setup | P1 (completeness) | Empty catalog at launch = useless drug search; ANVISA data is public and free | Empty catalog (incomplete at launch) |
| 7 | CEO | Add prescription audit trail via existing AuditLog | P4 (DRY) | AuditLog model exists in apps/core/ from Sprint 1; reuse instead of separate prescription log | New prescription event log (duplication) |
| 8 | CEO | MEMED integration: not this sprint | P3 (pragmatic) | MEMED requires partnership/API access evaluation; proprietary builder ships faster and gives full control for MVP pilot | MEMED integration (dependency risk, unknown API access) |
| 9 | Eng | Drug search: one endpoint at /api/v1/pharmacy/drugs/search/ | P4 (DRY) | Used by both prescribing UI and catalog — one endpoint, not two | Separate emr/drugs/search/ proxy (duplication) |
| 10 | Eng | Extract SignableMixin from ClinicalDocument, share with Prescription | P4 (DRY) | `ClinicalDocument.sign()` (emr/models.py:344-351) is the source of truth — NOT SOAPNote (SOAPNote has no signing logic). Mixin: `sign()`, `signed_at`, `signed_by`, `is_signed`, model-level immutability guard. ~50 LOC saved, prevents drift | Duplicate signing logic per model |
| 11 | Eng | Timeline: cursor pagination from day 1, LIMIT 50 | P1 (completeness) | 200+ events per patient is realistic; no pagination = O(N) query on every load | Defer pagination (tech debt immediately) |
| 12 | Eng | BNAFAR import: bulk_create(update_conflicts=True) | P5 (explicit) | ~80k ANS drug entries; loop of update_or_create = 20min import; bulk = seconds | update_or_create loop (impractical at scale) |
| 13 | Eng | Migration dependency: pharmacy.0001_initial before emr prescription FK migration | P5 (explicit) | Cross-app FK requires explicit migration dependency declaration | Undeclared dependency (migration failure) |
| 14 | Design gate | Prescription Builder: auto-create draft on tab open | User (taste) | Consistent with SOAPEditor pattern; eliminates extra click on every consultation | Explicit "Nova Prescrição" button (friction on most-used path) |
| 15 | Design gate | Timeline icon mapping: Stethoscope/Pill/FileText/Activity/Calendar/Package | User (taste) | Specified now to prevent visual inconsistency; uses lucide-react (already in dep tree) | Leave to builder (risk of wrong icon set) |
| 16 | CEO re-review | PrescriptionViewSet: `prefetch_related('items', 'items__drug')` required | P5 (explicit) | Without it: 60 queries per prescription list load (10 prescriptions × 5 items) — mirrors EncounterViewSet pattern | Unspecified (N+1 discovered in prod) |
| 17 | CEO re-review | PDF generation: WeasyPrint server-side | P1 (completeness) | Browser print varies across devices; legal prescriptions need reliable archivable output. Add libpango/Cairo to Dockerfile. Phase 2: consider PDF archival storage. | Browser print CSS (no server deps but inconsistent across Chrome/Firefox/iPad) |

## Phase 2: Design Review

### Design Consensus Table

| Component | Score | Gaps | Auto-resolved | Taste call? |
|-----------|-------|------|---------------|-------------|
| Prescription Builder | 5/10 | New prescription flow (auto-create vs explicit button), free-text drug affordance when not found in catalog, sign success state feedback, post-sign drag-handle removal | — | Yes — see gate |
| Drug Catalog | 7/10 | Cross-tab search scope unclear (drugs vs materials), "Controlled only" filter chip missing | — | Minor |
| Patient Timeline | 6/10 | Icon-to-event-type mapping unspecified, date range picker type unspecified | — | Yes — see gate |

**Design findings incorporated into plan:** print template field list, status badge color mapping, WeasyPrint server-side PDF, controlled substance 🔴 badge, "Não encontrado — usar descrição livre" affordance note.

**CEO Re-Review — UX Flow Diagram:**

```
SPRINT 6 — USER FLOW (screens, states, transitions)

DOCTOR: Write Prescription (S-015)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Encounter Detail] → [Prescrição tab opens]
                              │
                    LOADING: auto-create draft
                              │
                    [Draft form renders]
                         │         │
                  [Drug search]  [Free text]
                   │       │
              "Buscando"  [Results dropdown]
              (300ms)       │   (keyboard: ↑↓ Enter Esc)
                            │
                    [Item added to list]
                    [Drag to reorder / ↑↓]
                            │
              ┌─────────────▼──────────────┐
              │     [Assinar Prescrição]   │
              └─────────────┬──────────────┘
                            │
                    [Confirm modal]
                    "ação irreversível"
                            │
              ┌─────────────▼──────────────┐
              │  SIGNING (disabled + spinner)│
              └────────┬────────┬───────────┘
                    SUCCESS   ERROR
                       │         │
               [Read-only view] [Toast + re-enable]
               status=Ativa
                       │
              ┌────────▼────────┐
              │   [Imprimir]    │
              └────────┬────────┘
                LOADING "Gerando PDF..."
                   │           │
                SUCCESS      ERROR
                   │           │
          [PDF in new tab]  [Toast + retry]

TIMELINE: Patient History (S-016)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Patient Detail] → [Histórico tab]
                         │
                  LOADING: skeleton rows
                         │
             ┌───────────┴────────────┐
           EMPTY                  RESULTS
             │                       │
"Nenhum evento clínico         [Vertical event list]
 registrado para {name}"        │              │
                               click        filter chips
                                │           (type + date)
                          [Event detail]  [Filtered list]

PHARMACIST: Drug Catalog (S-026)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[/farmacia/catalog] → [Drugs tab] / [Materials tab]
                            │
                   [Search bar (instant)]
                            │
               [Create drug] → [Edit modal] → [Save]
                  controlled toggle → control_type selector
```

---

## Phase 3: Engineering Review

### Eng Consensus Table

| Area | Finding | Severity | Resolution | Principle |
|------|---------|----------|------------|-----------|
| Drug search duplication | Plan had two endpoints (EMR proxy + pharmacy) | High | Consolidated at `/api/v1/pharmacy/drugs/search/` | DRY (#9) |
| Signing pattern duplication | ClinicalDocument and Prescription have same sign+immutable logic | Medium | Extract `SignableMixin` to `apps/core/` — source is `ClinicalDocument.sign()`, not SOAPNote | DRY (#10) |
| Timeline pagination | No pagination = O(N) query at 200+ events | High | Cursor pagination + LIMIT 50 from day 1 | Completeness (#11) |
| BNAFAR import perf | `update_or_create` loop → 20min for 80k rows | High | `bulk_create(update_conflicts=True)` on `anvisa_code` | Explicit (#12) |
| Migration ordering | Cross-app FK without declared dependency → migration failure | Critical | Explicit `dependencies=[('pharmacy','0001_initial')]` | Explicit (#13) |
| Sign race condition | Concurrent item creates during sign window | Medium | Wrap sign in `select_for_update()` on Prescription row | Completeness (auto-applied) |
| Prescription N+1 | PrescriptionViewSet returns items+drug without prefetch → 60 queries for 10 prescriptions × 5 items | High | `PrescriptionViewSet.get_queryset()` must use `prefetch_related('items', 'items__drug')` — mirror EncounterViewSet pattern | Completeness (#16) |
| Test coverage | Prescription signing, BNAFAR import, timeline pagination | High | Full test plan generated | Completeness |

**Test plan artifact:** `~/.gstack/projects/tropeks-Vitali/master-sprint6-test-plan-20260327-150207.md`
Coverage: 31 backend test cases, 12 frontend RTL tests, 3 Playwright E2E flows, migration checklist, 3 performance benchmarks.

**CEO Review — 4 additional test cases required (Sections 2/4/6 gaps):**
- `test_drug_search_falls_back_to_icontains_when_pg_trgm_unavailable` — mock `Drug.objects.annotate()` to raise `ProgrammingError`, assert results still returned via `icontains` (covers Gap 2 fix)
- `test_seed_bnafar_handles_windows1252_encoding` — pass Latin-1 encoded fixture CSV to `seed_bnafar`, assert drugs imported correctly (covers Gap 3 chardet fix)
- `test_patient_cpf_nullable_for_foreign_nationals` — `Patient.objects.create(..., cpf=None)` must not raise after CPF nullable migration (covers Gap 4 + Gap 7 migration)
- RTL: `test_drug_search_shows_retry_on_network_error` — mock `fetch` to reject during drug search, assert retry button renders (covers Gap 4 UX fix)

**Auto-applied eng decisions:** select_for_update() on sign (#Failure Modes Registry), all 5 decisions above (logged in audit trail).

---

## Phase 4: CEO Re-Review Outputs

### What Already Exists (Sprint 6 depends on these)

| Existing artifact | Location | Reuse plan |
|---|---|---|
| `AuditLog.save()` immutability guard | `apps/core/models.py:301-305` | Blueprint for `Prescription.save()` override |
| `ClinicalDocument.sign()` signing logic | `apps/emr/models.py:344-351` | Source for `SignableMixin` extraction |
| `log_audit()` function | `apps/emr/views.py:27` | Reuse for all 5 prescription audit events |
| `PatientViewSet.timeline` action (stub) | `apps/emr/views.py:83-100` | Extend — do not create a second endpoint |
| `EncounterViewSet.get_queryset()` prefetch pattern | `apps/emr/views.py:294-298` | Mirror with `prefetch_related('items','items__drug')` in PrescriptionViewSet |
| SOAPEditor 800ms debounce autosave | `frontend/components/encounters/SOAPEditor.tsx` | Reuse pattern (not the function) in PrescriptionBuilder |
| `Role`, `Permission`, `User` | `apps/core/` Sprint 1 | Reuse for `pharmacy.read`, `pharmacy.dispense_controlled` permissions |

### Dream State Delta (12-month ideal vs Sprint 6)

Sprint 6 delivers: create prescription → sign → print. The clinical loop is closed at the basic level.

What's missing from the ideal state:
- **ICP-Brasil digital signature** — SHA-256 hash is MVP; prescriptions don't have legal e-prescription standing without it. Phase 2.
- **SNGPC controlled substance reporting** — ANVISA Portaria 344 compliance requires electronic reporting. Phase 2.
- **Stock + Dispensation (Sprint 7)** — pharmacist can't dispense against Sprint 6 prescriptions until stock module ships.
- **Drug interaction checking** — Sprint 9 (AI Clinical Safety Net). No safety guardrails at prescribe-time in Sprint 6.
- **PDF archival storage** — WeasyPrint regenerates on every print; no stored PDF archive. Phase 2 if clinics need audit-proof archived PDFs.
- **Offline capability** — Brazilian clinics with unreliable connectivity; no offline mode for prescriptions.

### Error & Rescue Registry

| Method | Exception | Rescued? | HTTP Status | Rescue Action | User Sees |
|--------|-----------|----------|-------------|---------------|-----------|
| `Prescription.save()` (post-sign mutate) | `PermissionDenied` | ✓ | 403 | ViewSet returns 403 JSON | "Prescrição assinada não pode ser editada" |
| `PrescriptionViewSet.sign()` select_for_update timeout | `OperationalError` | ✗ | 500 | **CRITICAL GAP** — unhandled | Generic 500 error |
| `Drug.objects.annotate(TrigramSimilarity)` | `ProgrammingError` (no pg_trgm) | ✓ | 200 | Fallback to `icontains` | No visible error, slightly worse results |
| `seed_bnafar` encoding detection | `UnicodeDecodeError` | ✓ | n/a | Retry with chardet-detected encoding | No user impact (mgmt command) |
| `seed_bnafar` duplicate `anvisa_code` | `IntegrityError` | ✓ | n/a | `update_conflicts=True` | No duplicates |
| `PrescriptionViewSet.cancel()` (already dispensed) | `ValidationError` | ✓ | 400 | Returns 400 JSON | "Não é possível cancelar prescrição já dispensada" |
| WeasyPrint PDF generation | `WeasyPrintError` / OOM | ✗ | 500 | **GAP** — catch `WeasyPrintError`, return 500 JSON | "Erro ao gerar prescrição" toast on frontend |
| `PatientViewSet.timeline()` aggregation | `OperationalError` (timeout) | ✗ | 500 | **GAP** — unhandled | Error toast if implemented, else silent |
| `dispensation.create()` stock insufficient | `ValidationError` | ✓ | 409 | Returns 409 JSON | "Estoque insuficiente" (Sprint 7) |
| `select_fefo_lot()` no lot available | Returns `None` | ✓ | 409 | ViewSet null-checks | "Nenhum lote disponível" (Sprint 7) |

**Critical gaps (add to implementation checklist):**
- Wrap `sign()` lock acquisition in `try/except OperationalError` → return 503 with "Tente novamente em instantes"
- Catch `WeasyPrintError` in print view → return `{"error": "pdf_generation_failed"}` with 500
- Wrap timeline aggregation in `try/except` → return 503 with retry flag

### Completion Summary

```
+====================================================================+
|          MEGA PLAN RE-REVIEW — COMPLETION SUMMARY (CEO)            |
+====================================================================+
| Mode selected        | HOLD SCOPE (maximum rigor)                  |
| System Audit         | Settings, Dockerfile, BNAFAR deps verified  |
| Step 0               | HOLD SCOPE — no new features, fix the plan  |
| Section 1  (Arch)    | 0 new issues (prior review clean)           |
| Section 2  (Errors)  | 3 CRITICAL GAPS added to Error Registry     |
| Section 3  (Security)| 0 new issues                                |
| Section 4  (Data/UX) | 2 issues: CPF nullable, foreign nationals   |
| Section 5  (Quality) | 3 issues: SignableMixin source, api.ts, CPF |
| Section 6  (Tests)   | 4 test cases added                          |
| Section 7  (Perf)    | 1 issue: PrescriptionViewSet N+1            |
| Section 8  (Observ)  | 2 gaps: audit events + seed_bnafar logging  |
| Section 9  (Deploy)  | 3 risks: runbook, pg_trgm PaaS, seed order  |
| Section 10 (Future)  | Reversibility: 3/5, 1 debt item resolved    |
| Section 11 (Design)  | 4 UX state gaps fixed, UX flow diagram added|
+--------------------------------------------------------------------+
| NOT in scope         | written (8 items)                           |
| What already exists  | written (7 artifacts)                       |
| Dream state delta    | written (6 gaps to 12-month ideal)          |
| Error/rescue registry| 10 methods, 3 CRITICAL GAPS                 |
| Failure modes        | 14 total, all accounted for                 |
| TODOS.md updates     | 1 item proposed below                       |
| Scope proposals      | 0 (HOLD SCOPE mode)                         |
| CEO plan             | skipped (HOLD SCOPE)                        |
| Outside voice        | skipped                                      |
| Lake Score           | 13/13 recommendations chose complete option |
| Diagrams produced    | 1 (UX flow — screens/states/transitions)    |
| Stale diagrams found | 1 — Architecture diagram SOAPNote ref fixed |
| Unresolved decisions | 0                                           |
+====================================================================+
```

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 2 | CLEAR (HOLD SCOPE) | 17 decisions logged; 13 gaps fixed across Sections 5–11; 3 critical error paths added to registry; 1 TODO added |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | SKIPPED | Codex CLI unavailable in environment |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 5 arch gaps resolved, test plan written, 1 critical race condition fixed |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | DONE_WITH_CONCERNS | PrescriptionBuilder 5/10 and Timeline 6/10 — taste calls resolved at gate |

**UNRESOLVED:** 0
**VERDICT:** CLEARED — CEO + ENG CLEARED. All reviews complete at commit db0813a. 17 decisions logged. Plan is implementation-ready.
