<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260330-134640.md -->
<!-- autoplan: tropeks-Vitali / master / d9ef4ca / 2026-03-30 -->

# Sprint 7 Plan — Pharmacy & Inventory (E-007)

**Branch:** master
**Sprint:** 7
**Epic:** E-007 — Pharmacy & Inventory
**Stories:** S-026, S-027, S-028
**Total points:** 21 (5 + 8 + 8)
**Design doc:** `~/.gstack/projects/tropeks-Vitali/halfk-master-design-20260328-145944.md`

---

## Goal

Deliver end-to-end pharmacy management for the pilot clinic: drug/material catalog, stock tracking by lot and expiry date, and prescription-linked dispensation with FEFO lot selection. After this sprint, a farmacêutico can search the drug catalog, view stock levels with expiry alerts, and dispense medications against signed prescriptions — with stock automatically decremented.

**Explicit out-of-scope:**
- Purchase orders and supplier management (S-029 → Sprint 11)
- TUSS billing linkage for materials (belongs in Sprint 6 / already done)
- Drug interaction checking (Phase 2)
- Barcode scanner hardware integration (Phase 2)

---

## Stories

### S-026 — Drug & Material Catalog (5 pts)

**Acceptance Criteria:**
- Drug registry with: nome comercial, princípio ativo, manufacturer, presentation, barcode, ANVISA code, controlled substance flag (Portaria 344 list: A1, B1, C1, etc.), requires_prescription
- Material registry with: name, description, category, barcode, unit, optional TUSS code
- Fuzzy search on name, generic_name, barcode (pg_trgm)
- CRUD API (admin + farmacêutico roles)
- Frontend: catalog management pages (drug list + detail, material list + detail)

**Tasks:**
- [ ] `Drug` model + migration (see DATA_MODEL.md §5)
- [ ] `Material` model + migration
- [ ] `DrugSerializer`, `MaterialSerializer` with validation
- [ ] `DrugViewSet`, `MaterialViewSet` (CRUD, filter, search)
- [ ] URL routing: `/api/v1/pharmacy/drugs/`, `/api/v1/pharmacy/materials/`
- [ ] Permission: `pharmacy.catalog_manage` (admin, farmacêutico)
- [ ] Frontend: `/pharmacy/drugs/` — list + search page
- [ ] Frontend: `/pharmacy/drugs/new` — create form
- [ ] Frontend: `/pharmacy/drugs/[id]` — detail/edit page
- [ ] Frontend: `/pharmacy/materials/` — list + search page
- [ ] Tests: CRUD, fuzzy search, controlled substance validation, permission gates

---

### S-027 — Stock Management (8 pts)

**Acceptance Criteria:**
- Track stock by item + lot + expiry date (StockItem)
- All movements logged as append-only StockMovement records (entry, exit, adjustment, return, loss)
- Min/max stock alerts (flag when quantity < min_stock)
- Expiry alerts: items expiring within 30 / 60 / 90 days
- Celery Beat tasks: daily expiry alert checker, daily min-stock alert checker
- Frontend: stock dashboard with alerts, stock movement history per item

**Tasks:**
- [ ] `StockItem` model + migration
- [ ] `StockMovement` model + migration (append-only, no updates/deletes)
- [ ] `StockItemSerializer`, `StockMovementSerializer`
- [ ] `StockItemViewSet` (list/retrieve/create, no update — update via movements)
- [ ] `StockMovementViewSet` (create only — append-only)
- [ ] Stock adjustment API: `POST /api/v1/pharmacy/stock/{id}/adjust/`
- [ ] Current level query: `GET /api/v1/pharmacy/stock/?drug={id}` → aggregated quantity by lot
- [ ] Celery task: `check_expiry_alerts` (daily, flags items expiring ≤ 90 days)
- [ ] Celery task: `check_min_stock_alerts` (daily, flags items < min_stock)
- [ ] Alert model or endpoint: expose active alerts to frontend
- [ ] Frontend: `/pharmacy/stock/` — dashboard with low-stock + expiry alerts
- [ ] Frontend: `/pharmacy/stock/[id]/` — item detail with movement history
- [ ] Frontend: Stock entry form (manual entry + lot number + expiry date)
- [ ] Tests: stock movement ledger integrity, FEFO ordering, expiry alert logic, min-stock trigger

---

### S-028 — Dispensation (8 pts)

**Acceptance Criteria:**
- Dispense medication from a signed prescription item
- Prescription must be signed before dispensation is allowed
- Stock decremented using FEFO (First Expiry First Out) — earliest expiry lot selected first
- Controlled substance workflow: requires `farmacêutico` role + additional notes field
- Dispensation record links: prescription, prescription_item, patient, lot (StockItem), user, quantity, dispensed_at
- Cannot dispense more than prescribed quantity
- Cannot dispense if insufficient stock across all lots
- Frontend: dispensation interface — search prescription → show items → select lot (auto FEFO) → confirm → dispense

**Data Model Note — Multi-Lot FEFO:**
A single dispensation may span multiple lots when requested quantity > any single lot's available quantity. The original `Dispensation` model (single `stock_item_id` FK) cannot represent this. Fix: replace with a through-table.

```python
class Dispensation(models.Model):
    prescription_id = FK(Prescription)
    prescription_item_id = FK(PrescriptionItem)
    patient_id = FK(Patient)
    dispensed_by_id = FK(User)
    quantity = DecimalField(10,2)        # total quantity dispensed this transaction
    notes = TextField(blank=True)       # controlled substance notes (required for controlled)
    dispensed_at = auto_now_add
    # NO stock_item_id FK here — lots tracked in DispensationLot

class DispensationLot(models.Model):
    dispensation_id = FK(Dispensation, related_name='lots')
    stock_item_id = FK(StockItem)       # one row per lot consumed
    quantity = DecimalField(10,2)       # quantity taken from this lot
```

**Dispensation Flow UI Spec:**

**Step 1 — Search:** Search bar accepts prescription ID, patient name, or patient CPF. Results show card: `[Patient name] • [Prescription date] • [Prescribing doctor] • [Status badge: signed ✓ / unsigned ⚠]`. Unsigned prescriptions appear in results with a locked state (greyed row, tooltip "Receita não assinada"). Do not filter them out.

**Step 2 — Item list:** Shows each PrescriptionItem with columns: Drug name | Dosage | Prescribed | Remaining (sum of prior dispensations) | Status. "Remaining" is the primary displayed quantity, not "Prescribed." Already fully dispensed items show `bg-gray-100 text-gray-400` (neutral).

**Step 3 — Lot allocation (auto FEFO, read-only):** After entering dispatch quantity, show a read-only breakdown: `Lote ABC • Validade: 03/2027 • Qtd: 60 comp` + additional lot rows if FEFO spans lots. Small "Alterar" ghost link (out of scope for pilot — show as disabled). This is a visual confirm step, not an interactive selector.

**Step 4 — Confirm modal:** Summary card: patient + drug name + total quantity + lot breakdown. Controlled substance: `<textarea required placeholder="Registro de dispensação controlada (Portaria 344)">` must be non-empty before "Dispensar" button enables. Non-controlled: button always enabled.

**Step 5 — Post-confirm:** Success toast `"Dispensação registrada"` + stay on the prescription item list (allowing next item to be dispensed).

**Client-side pre-validation:** Before confirm button activates, client checks: SUM(available across all lots) ≥ requested quantity. If not, show yellow warning inline: `"Estoque insuficiente: X disponíveis"`. Do not allow submit.

**Tasks:**
- [ ] `Dispensation` + `DispensationLot` models + migration (replace original single-FK design)
- [ ] FEFO lot selection: `StockItem.objects.filter(drug=item.drug, quantity__gt=0, expiry_date__gte=today).order_by('expiry_date').select_for_update()` — greedily fill from earliest-expiry lot first; create one `DispensationLot` row per lot consumed
- [ ] Dispensation serializer with validation:
  - prescription must be `signed` status
  - quantity ≤ remaining on prescription item
  - total available stock ≥ requested quantity
  - controlled = requires `farmacêutico` role
  - controlled + notes field empty = reject with "Registro de dispensação controlada obrigatório"
  - total requested qty ≤ SUM(stock_item.quantity) across all lots
- [ ] `DispensationViewSet` (create + list)
- [ ] URL: `POST /api/v1/pharmacy/dispensations/`
- [ ] Stock decrement: create `StockMovement(type='exit')` per DispensationLot row on commit
- [ ] AuditLog: log dispensation create (financial + clinical record)
- [ ] API: `GET /api/v1/emr/prescriptions/?status=signed&patient={id}` — for prescription search in dispensation flow
- [ ] API: `GET /api/v1/pharmacy/stock/availability/?drug={id}&quantity={n}` — client-side pre-validation endpoint returning lot breakdown + total available
- [ ] Frontend: `/pharmacy/dispensation/` — 5-step flow per spec above (search → items → lots → confirm → success)
- [ ] Frontend: Stock dashboard per design spec: 4 KPI cards (expiring 30/60/90d, below-min) + alert table + full stock table
- [ ] Frontend: Drug list — columns: Nome comercial | Princípio ativo | Apresentação | Controlado (orange dot badge) | Ações
- [ ] Frontend: Drug/material search — 300ms debounced combobox (same pattern as TUSSCodeSearch)
- [ ] Frontend: ANVISA code + barcode in `font-mono text-sm text-gray-600`
- [ ] Frontend: All pages — loading skeleton (`animate-pulse`), error banner with retry, success toast
- [ ] Tests: FEFO multi-lot selection, partial dispensation, controlled substance gate, insufficient-stock rejection, double-dispense prevention, DispensationLot ledger accuracy

---

## Architecture

### Backend: `apps/pharmacy/`

```
apps/pharmacy/
  models.py         — Drug, Material, StockItem, StockMovement, Dispensation
  serializers.py    — per-model serializers + FEFO validation
  views.py          — DrugViewSet, MaterialViewSet, StockItemViewSet, StockMovementViewSet, DispensationViewSet
  urls.py           — router registration
  tasks.py          — check_expiry_alerts, check_min_stock_alerts (Celery)
  admin.py          — Django admin for catalog management
  tests/
    test_catalog.py
    test_stock.py
    test_dispensation.py
  migrations/
    0001_initial.py
```

### Frontend: `frontend/app/(dashboard)/pharmacy/`

```
pharmacy/
  drugs/
    page.tsx          — drug list + search
    new/page.tsx      — create drug
    [id]/page.tsx     — drug detail + edit
  materials/
    page.tsx
    new/page.tsx
    [id]/page.tsx
  stock/
    page.tsx          — stock dashboard (alerts + levels)
    [id]/page.tsx     — item detail + movements
  dispensation/
    page.tsx          — dispensation interface
```

### Permissions

| Role | catalog_manage | stock_manage | dispense_standard | dispense_controlled |
|------|---------------|--------------|-------------------|---------------------|
| admin | ✓ | ✓ | ✓ | ✓ |
| farmacêutico | ✓ | ✓ | ✓ | ✓ |
| enfermeiro | — | — | ✓ | — |
| medico | — | — | — | — |
| recepcionista | — | — | — | — |
| faturista | — | — | — | — |

### Celery Beat Integration

Both alert tasks go in `CELERYBEAT_SCHEDULE` (in `vitali/settings/base.py` or `celery.py`):

```python
'check-expiry-alerts': {
    'task': 'apps.pharmacy.tasks.check_expiry_alerts',
    'schedule': crontab(hour=6, minute=0),  # 6am daily
},
'check-min-stock-alerts': {
    'task': 'apps.pharmacy.tasks.check_min_stock_alerts',
    'schedule': crontab(hour=6, minute=15),  # 6:15am daily
},
```

### EMR Integration Point

`Dispensation.prescription_id → apps.emr.Prescription`
`Dispensation.prescription_item_id → apps.emr.PrescriptionItem`

The pharmacy app reads from EMR but never writes to it. EMR models are already implemented.

---

---

## Architecture Notes — Engineering Fixes

### Fix 1: Migration Order Dependency

`apps/emr/migrations/0002_add_prescription.py` must declare:
```python
dependencies = [
    ('emr', '0001_initial'),
    ('pharmacy', '0001_initial'),  # Drug model must exist before PrescriptionItem.drug FK
]
```

Also add a `pre_delete` signal on `Drug` that checks for live `PrescriptionItem` references (same pattern as `core/signals.py`).

### Fix 2: FEFO Transaction Pattern (Critical — prevents negative stock)

```python
def _dispense_fefo(drug, requested_qty, dispensation):
    today = date.today()
    with transaction.atomic():
        # Lock AFTER entering atomic, filter on expiry only — re-check qty inside lock
        lots = StockItem.objects.select_for_update(of=('self',)).filter(
            drug=drug,
            expiry_date__gte=today,
        ).order_by('expiry_date')

        # Re-evaluate quantities AFTER lock is held
        available = [(lot, lot.quantity) for lot in lots if lot.quantity > 0]
        total_avail = sum(q for _, q in available)
        if total_avail < requested_qty:
            raise ValidationError("Estoque insuficiente")

        remaining = requested_qty
        for lot, qty in available:
            if remaining <= 0:
                break
            take = min(qty, remaining)
            DispensationLot.objects.create(dispensation=dispensation, stock_item=lot, quantity=take)
            StockMovement.objects.create(stock_item=lot, type='exit', quantity=-take, ...)
            StockItem.objects.filter(pk=lot.pk).update(quantity=F('quantity') - take)
            remaining -= take
```

### Fix 3: DEFAULT_ROLES permission strings (Critical — without this, all pharmacy endpoints return 403)

Add to `apps/core/permissions.py` or `DEFAULT_ROLES` seeding:

```python
'farmaceutico': [
    'pharmacy.read', 'pharmacy.catalog_manage', 'pharmacy.stock_manage',
    'pharmacy.dispense', 'pharmacy.dispense_controlled',
],
'enfermeiro': ['pharmacy.read', 'pharmacy.dispense'],
'admin': ['pharmacy.read', 'pharmacy.catalog_manage', 'pharmacy.stock_manage',
          'pharmacy.dispense', 'pharmacy.dispense_controlled'],
```

**This must be added to S-026 tasks, not left implicit.**

### Fix 4: Celery Task Tenant Context (Critical — crashes on first real execution)

```python
from django_tenants.utils import get_tenant_model, schema_context

@app.task
def check_expiry_alerts():
    today = date.today()
    for tenant in get_tenant_model().objects.exclude(schema_name='public'):
        with schema_context(tenant.schema_name):
            alerts = {
                'expiring_30': list(StockItem.objects.filter(
                    expiry_date__lte=today + timedelta(days=30),
                    expiry_date__gte=today, quantity__gt=0
                ).values('id', 'drug__name', 'lot_number', 'expiry_date', 'quantity')),
                'expiring_60': [...],
                'expiring_90': [...],
                'generated_at': timezone.now().isoformat(),
            }
            cache.set(f'pharmacy:{tenant.schema_name}:expiry_alerts', alerts, timeout=90000)
```

### Fix 5: StockItem.quantity + StockMovement Atomicity

`StockMovement.save()` must update `StockItem.quantity` using `F()` expression inside `transaction.atomic()`. Enforce append-only via:

```python
class StockMovement(models.Model):
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("StockMovement entries are immutable.")
        with transaction.atomic():
            super().save(*args, **kwargs)
            delta = self.quantity  # positive = entry, negative = exit
            StockItem.objects.filter(pk=self.stock_item_id).update(
                quantity=F('quantity') + delta,
                updated_at=timezone.now()
            )

    def delete(self, *args, **kwargs):
        raise ValueError("StockMovement entries cannot be deleted.")
```

### Fix 6: Dispensation.quantity → remove denormalization

Remove `Dispensation.quantity` field. Compute as `SUM(DispensationLot.quantity)` via property:

```python
@property
def total_quantity(self):
    return self.lots.aggregate(total=Sum('quantity'))['total'] or 0
```

This eliminates divergence risk (finding 5b from engineering review).

---

## Open Questions

1. **Alert storage:** Where do we surface active alerts? Options: (a) dedicated `StockAlert` model, (b) computed on-the-fly from StockItem query, (c) Redis-cached flag per tenant. Option (b) is simplest — the daily tasks just query and send notifications (no persistent alert model needed for pilot).

2. **Notification channel for alerts:** Email? Dashboard-only? For pilot: dashboard badge only (no email). Celery task updates a Redis key with alert count. Frontend polls on page load.

3. **Partial dispensation:** Can a prescription item be dispensed in multiple batches (e.g., 30 tabs today, 30 next week)? Design says yes — track remaining via SUM(dispensed_quantity) per prescription_item_id. Block when total ≥ prescribed quantity.

4. **`farmacêutico` role:** Verify it exists in `create_tenant.py` role seeding. Add if missing.

5. **ANVISA controlled list:** Portaria 344/98 control types (A1, A2, A3, B1, B2, C1, C2, C3, D1, D2, E). Store as `control_type: VARCHAR(10)` with validation against these values. No full ANVISA import needed for pilot — flag manually when creating catalog entries.

---

---

## Test Plan

**File:** `~/.gstack/projects/tropeks-Vitali/halfk-master-pharmacy-test-plan-20260330.md`

| Test | Type | Story | Critical? |
|------|------|-------|-----------|
| Drug create with controlled flag + ANVISA code | Unit | S-026 | — |
| Drug create duplicate barcode → unique error | Unit | S-026 | — |
| Drug fuzzy search (pg_trgm, partial name) | Integration | S-026 | — |
| Drug list → farmacêutico 200, recepcionista 403 | Integration | S-026 | ✓ |
| `pharmacy.catalog_manage` in farmacêutico DEFAULT_ROLES | Unit | S-026 | ✓ |
| Stock entry creates StockMovement (append-only) | Integration | S-027 | ✓ |
| StockMovement update attempt → raises ValueError | Unit | S-027 | ✓ |
| StockItem.quantity increments via F() in StockMovement.save() | Integration | S-027 | ✓ |
| expiry_date < today on entry → validation error | Unit | S-027 | — |
| check_expiry_alerts runs with schema_context per tenant | Unit | S-027 | ✓ |
| check_expiry_alerts populates Redis key with item data | Integration | S-027 | — |
| check_min_stock_alerts triggers when quantity < min_stock | Integration | S-027 | — |
| FEFO selects earliest non-expired lot first | Unit | S-028 | ✓ |
| FEFO spans multiple lots → creates N DispensationLot rows | Integration | S-028 | ✓ |
| FEFO: quantity filter evaluated inside lock (no negative stock) | Integration | S-028 | ✓ |
| Dispense against unsigned Rx → 400 | Integration | S-028 | ✓ |
| Dispense controlled by enfermeiro → 403 | Integration | S-028 | ✓ |
| Dispense controlled without notes field → 400 | Integration | S-028 | ✓ |
| Dispense > available stock (all lots) → 400 | Integration | S-028 | ✓ |
| Dispense exactly fills lot → StockItem.quantity = 0 | Integration | S-028 | — |
| Dispensation.total_quantity == SUM(DispensationLot.quantity) | Unit | S-028 | — |
| Prescription sign action requires emr.sign role | Integration | S-015 | ✓ |
| PrescriptionItem.generic_name auto-populated from drug | Unit | S-015 | — |
| Migration: pharmacy 0001 before emr 0002 | Integration | S-026 | ✓ |
| stock/availability/ endpoint requires IsAuthenticated | Integration | S-027 | ✓ |

---

## Success Criteria

Sprint 7 is DONE when:

1. A farmacêutico can create a drug entry with controlled substance flag and ANVISA code.
2. A stock entry creates a StockMovement and increments quantity on the StockItem.
3. A signed prescription can be dispensed — stock decrements, Dispensation record created, FEFO lot selected automatically.
4. An attempt to dispense an unsigned prescription returns 400.
5. An attempt to dispense more than available stock returns 400.
6. Dispensing a controlled substance without `farmacêutico` role returns 403.
7. Celery tasks `check_expiry_alerts` and `check_min_stock_alerts` execute without error in test.
8. All test files pass: `pytest apps/pharmacy/tests/ -v` — 0 failures.
9. `/pharmacy/*` routes return 403 for `medico` and `recepcionista` roles.

---

---

## S-015 (Minimal) — Prescription Model (added to Sprint 7 scope)

**Scope:** Minimal structured prescription model required for S-028 (Dispensation) to function. Does NOT include: prescription builder UI, print view, PDF generation (deferred to Sprint 7b or Sprint 8 full S-015 implementation).

**Tasks:**
- [ ] `Prescription` model in `apps/emr/models.py`:
  - `patient_id` (FK → Patient)
  - `encounter_id` (FK → Encounter, nullable)
  - `prescribed_by_id` (FK → core.User)
  - `status` ENUM: `draft`, `signed`
  - `signed_at` (DateTimeField, nullable)
  - `signed_by_id` (FK → core.User, nullable)
  - `notes` (TextField, optional)
  - `created_at`, `updated_at`
- [ ] `PrescriptionItem` model in `apps/emr/models.py`:
  - `prescription_id` (FK → Prescription)
  - `drug_id` (FK → apps.pharmacy.Drug — cross-app FK, read-only from EMR)
  - `generic_name` (CharField — denormalized for display if drug changes)
  - `dosage` (CharField — "500mg 2x ao dia")
  - `route` (CharField — "oral", "IV", "IM", "tópico")
  - `duration_days` (IntegerField, nullable)
  - `quantity` (DecimalField — units to dispense)
  - `unit` (CharField — "comp", "frasco", "ml")
- [ ] `PrescriptionSerializer`, `PrescriptionItemSerializer`
- [ ] `PrescriptionViewSet` (CRUD + sign action: `POST /api/v1/emr/prescriptions/{id}/sign/`)
- [ ] URL: `/api/v1/emr/prescriptions/`
- [ ] Migration (alongside pharmacy models)

**Note:** `Drug` FK from EMR → Pharmacy creates a cross-app dependency. This is acceptable (EMR already depends on Pharmacy in the architecture doc). The FK is enforced at app level, not DB level (same as billing's TUSSCode cross-schema pattern).

---

## CEO Review Findings

### Error & Rescue Registry

| Failure mode | Impact | Rescue |
|---|---|---|
| Concurrent dispensation race | Phantom over-dispense | `select_for_update()` on StockItem rows during FEFO selection |
| Stock decrement without commit | Phantom stock loss | `transaction.atomic()` around dispense + StockMovement create |
| Double-dispense (user clicks twice) | Over-dispense | Idempotency key or check: SUM(dispensed_qty) per prescription_item ≥ requested |
| Dispensing from expired lot | Expired medication | FEFO query filters `expiry_date >= today` |
| Controlled substance by wrong role | Portaria 344 violation | `validate()` in serializer checks `user.role.has_perm('pharmacy.dispense_controlled')` |
| Celery task silent failure | No alerts sent | Structured logging + Sentry integration (existing infra) |

### CEO Concerns (from Codex voice + primary review)

**P2 — Controlled substance compliance:** Portaria 344/98 requires a specific log format for controlled drug dispensation. "AuditLog + notes field" satisfies pilot but not production audit. Flag for Sprint 7b.

**P2 — FEFO without expiry date validation at entry:** Stock entry doesn't validate that expiry_date is in the future. Adding that validation to S-027 tasks.

**P3 — No charge capture linkage:** Dispensed items don't auto-create billing guide items. Acceptable for pilot. Sprint 8 or 9 integration point.

**P3 — Codex "build for pilot demand" reframe:** Noted. Sprint 7 builds the complete foundation. Kill criteria for pharmacy expansion: pilot uses dispensation in first 30 days post-deploy.

### Dream State Delta

This plan closes the pharmacy gap for pilot (dispensation demo-able). What's left for 12-month ideal:
- Purchase orders (S-029 → Sprint 11)
- Drug interaction checking (Phase 2)
- Charge capture: dispensed items → TISS guide items (Phase 2)
- Barcode scanner at dispensation (Phase 2)

---

## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Add Prescription + PrescriptionItem to Sprint 7 scope | P1 (completeness) + P2 (boil lake) | S-028 Dispensation is blocked without Prescription model. S-015 was never built. Adding minimal model is ~5 pts, keeps dispensation shippable. | Defer S-028 (leaves workflow broken), use ClinicalDocument hack (tech debt) |
| 2 | CEO | Approve full 3-story scope (S-026 + S-027 + S-028 + minimal S-015) | P1 (completeness) | Pilot demo requires end-to-end: catalog → stock → dispense. Catalog alone is a dead end. | S-026 + S-027 only (13 pts, incomplete workflow) |
| 3 | CEO | Add `select_for_update()` to FEFO selection in S-028 | P5 (explicit) + correctness | Race condition: two concurrent dispenses can select same lot, over-decrement. Standard fix. | Optimistic locking (more complex, no benefit at pilot scale) |
| 4 | CEO | Add expiry_date ≥ today validation to StockItem entry | P5 (explicit) | Prevent entering already-expired lots, which would corrupt FEFO logic silently. | Manual process control (not reliable) |
| 5 | CEO | Defer charge capture (dispensed items → TISS guide) to Phase 2 | P3 (pragmatic) | Not needed for pilot. Adds billing module coupling. Pharmacy value stands alone. | Add now (scope creep, billing coupling risk) |
| 6 | Design | Replace single `stock_item_id` FK with `DispensationLot` through-table | P5 (explicit) + correctness | FEFO dispense across multiple lots is impossible with a single FK. Critical data model bug. | Single-lot constraint (breaks FEFO when lot has insufficient qty) |
| 7 | Design | Specify dispensation as 5-step flow (search→items→lots→confirm→success) | P5 (explicit) | 3-word spec produces 6+ arbitrary implementer decisions. Named states prevent UX divergence. | Leave ambiguous (guarantees rework) |
| 8 | Design | Add stock dashboard layout spec (KPI cards → alert table → full table) | P1 (completeness) | Pharmacist mental model is "is anything on fire?" — alerts must be primary, not secondary. | Flat stock table with sidebar alerts (buries critical info) |
| 9 | Design | Add `GET /api/v1/pharmacy/stock/availability/` pre-validation endpoint | P5 (explicit) | Client-side pre-validation prevents post-submit frustration for pharmacist entering large quantities. | Server-only validation (bad UX: fill form → submit → error) |
| 10 | Design | Mandate debounced combobox pattern for drug/material search (same as TUSSCodeSearch) | P4 (DRY) | Pattern already exists in codebase. Duplicate = 2x code. | Per-page custom search input |
| 11 | Eng | Fix FEFO select_for_update: filter quantity AFTER lock, not before | P5 (explicit) + correctness | Filtering on qty__gt=0 before lock allows negative stock in concurrent dispensations. Critical correctness bug. | Optimistic locking (more complex, same race at pilot scale) |
| 12 | Eng | Add pharmacy permission strings to DEFAULT_ROLES before S-026 | P5 (explicit) | Without pharmacy.catalog_manage etc., all new endpoints return 403 for all roles. All tests will fail. | Add as afterthought at end of sprint (too late) |
| 13 | Eng | Add tenant context loop to Celery tasks | P1 (completeness) | Without schema_context per tenant, tasks crash on first execution in multi-tenant deployment. | Single-tenant assumption (breaks product promise) |
| 14 | Eng | Remove Dispensation.quantity field; use SUM(DispensationLot.quantity) | P5 (explicit) | Denormalized quantity can diverge from lot breakdown. Eliminates constraint-violation class of bugs. | Keep both + add clean() validator (more code, same risk) |
| 15 | Eng | StockMovement.save() wraps quantity update in F() + transaction.atomic() | P5 (explicit) + correctness | Stock count must be consistent with movement ledger. F() prevents read-then-write race. | Signal-based update (harder to test, same risk) |
| 16 | Eng | Prescription sign action explicit role check (emr.sign) | P5 (explicit) | Without it, any role with emr.read can sign prescriptions. Medication safety concern. | Model-level enforcement only (bypassed by direct save) |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | APPROVED_WITH_CONCERNS | 3 taste decisions, 2 critical gaps surfaced (prescription model, sequencing) |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | GATE: FAIL on settings.json wsl:* | 1 P1 finding (settings.local.json wsl:* permission) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 (via autoplan) | CLEAR | 4 critical blockers fixed: FEFO race, permissions, Celery tenant context, DispensationLot atomicity. 13 total findings. |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 (via autoplan) | APPROVED | Score 3/10 → 7/10. 5 decisions: DispensationLot model fix, 5-step flow spec, stock dashboard layout, combobox mandate, interaction states. |

**CODEX (design + eng):** Codex CEO found 5 strategic concerns (demand validation, sequencing, controlled substance compliance). Codex design found dispensation 3/10, multi-lot FEFO gap. Codex eng timed out — tagged subagent-only.

**UNRESOLVED (3 taste decisions, user chose to proceed):**
1. Sprint sequencing: pharmacy vs. AI TUSS first (user chose pharmacy)
2. S-028 in Sprint 7 vs. defer to Sprint 8 (user chose include)
3. Prescription scope: data model only vs. include minimal builder UI (deferred to user during implementation)

**VERDICT:** CLEARED — Eng Review passed. All 4 critical blockers addressed in plan. Implementation-ready. Next step: `/ship`.
