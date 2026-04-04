<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260402-183243.md -->
# Sprint 11 — Commercialization: Module Gating, Subscriptions & Pilot Readiness

**Status:** APPROVED
**Date:** 2026-04-02
**Branch:** feature/sprint11-commercialization
**Epics:** E-010 (Subscription & Feature Flags), E-007/S-029 (Purchase Orders), Pilot Polish
**Target users:** Platform admin (Vitali operator), Tenant admin (clinic owner), Farmacêutico
**Success metric:** A first-time faturista user can find the billing module, create a guide, and submit a batch within 30 minutes without assistance (internal setup does not count)

---

## Context

Sprint 10 shipped the Billing Intelligence Dashboard. Vitali now has 10 sprints of working product:
EMR, scheduling, pharmacy, billing, AI TUSS coding, and analytics.

The gap: none of it is gated. Every tenant on every plan gets every module. Before adding a second clinic to the pilot, we need to be able to say "you have billing but not pharmacy" — and the system must enforce it. Without module gating, Vitali is one database with no revenue model.

Sprint 11 closes this gap. Three stories:

**S-039 — Module Permission Layer:** `ModuleRequiredPermission` DRF class that checks the tenant's `FeatureFlag` table before any module endpoint responds. Apply to all billing, pharmacy, and AI endpoints. Frontend `useHasModule()` hook that hides nav items for inactive modules.

**S-040 — Platform Admin Subscription API:** REST API for managing Plans, PlanModules, and Subscriptions in the public schema. Platform admin can create a subscription for a tenant and activate/deactivate modules. This is the control plane for commercialization.

**S-041 — Tenant Subscription Status Page:** `/configuracoes/assinatura` page where tenant admin can see their current plan, active modules, and monthly price. No self-service module activation yet (handled by Vitali support) — just visibility.

**S-042 — Purchase Orders (basic):** Supplier + PurchaseOrder + PurchaseOrderItem models. PO creation and receiving flow (receiving creates StockMovements). Frontend PO management page under `/farmacia/compras`. Closes the pharmacy inventory loop: without POs, there's no tracked path for stock to enter the system beyond manual adjustments.

**S-043 — Pilot Readiness:** `seed_demo_data` management command that populates a tenant with realistic demo data (patients, guides, guides, stock items). Demo mode: a `DEMO_MODE=true` env flag that wraps all write endpoints in 403 with "Demo mode — read only." Useful for investor demos and pilot onboarding sessions.

---

## What Already Exists (Don't Rebuild)

| Sub-problem | Existing code |
|---|---|
| Tenant models | `core.Tenant`, `core.Domain` |
| Plan/Subscription models | `core.Plan`, `core.PlanModule`, `core.Subscription` (public schema) |
| Feature flag model | `core.FeatureFlag` + `tenant_has_feature()` in `middleware.py` |
| Feature flag middleware | `FeatureFlagMiddleware` attaches `request.has_feature()` |
| Active features API | `TenantFeaturesView` — `GET /api/v1/ai/tuss-sync-status/` returns active flags |
| RBAC permission class | `HasPermission` in `core.permissions` |
| Stock entry movement type | `StockMovement.MOVEMENT_TYPES` includes `('entry', 'Entrada')` |
| Pharmacy frontend | `/farmacia/` routes exist: catalog, stock, dispense |
| Auth + token | JWT-based auth, `getAccessToken()` in `lib/auth.ts` |

**NOT in scope:**
- Landing page / public marketing site (separate repo/concern)
- WhatsApp module (deferred — pivot from Sprint 10)
- Self-service module activation by tenant (needs payment integration)
- Payment gateway (Stripe/PagarMe) — subscription billing is manual for pilot
- ICP-Brasil digital signature
- DICOM/PACS

---

## Stories

### S-039 — Module Permission Layer

**Goal:** Module endpoints return 403 if the tenant's feature flag is off. Frontend hides UI for inactive modules.

**Acceptance criteria:**
- `ModuleRequiredPermission('billing')` applied to all billing app viewsets; returns 403 with `{"detail": "Module billing is not active for this tenant."}` if flag is off
- Same for pharmacy, ai_tuss modules
- `GET /api/v1/core/features/` returns `{"active_modules": ["emr", "billing"]}` for the current tenant
- Frontend `useHasModule(moduleKey)` hook reads from `/api/v1/core/features/` (cached in session)
- DashboardShell hides nav items for inactive modules (Billing, Farmácia, Analytics nav links)
- New tenants get `emr` flag enabled by default (via signal)

**Backend tasks:**

1. Move `tenant_has_feature` from `core/middleware.py` to a new `core/utils.py` (or add to existing). Both `middleware.py` and `permissions.py` import from `utils.py`. Do NOT import from `middleware.py` into `permissions.py` — circular import at startup.

   Add `ModuleRequiredPermission` to `backend/apps/core/permissions.py`:
   ```python
   from core.utils import tenant_has_feature  # NOT from middleware

   class ModuleRequiredPermission(BasePermission):
       def __init__(self, module_key: str):
           self.module_key = module_key
       def has_permission(self, request, view):
           if not request.user or not request.user.is_authenticated:
               return False
           if request.user.is_superuser:
               return True
           return tenant_has_feature(request.tenant, self.module_key)
   ```

2. Apply `ModuleRequiredPermission` to:
   - `billing/views.py` — all billing viewsets: add `ModuleRequiredPermission('billing')`
   - `pharmacy/views.py` — all pharmacy viewsets: add `ModuleRequiredPermission('pharmacy')`
   - `ai/views.py` — TUSS suggest + glosa predict: add `ModuleRequiredPermission('ai_tuss')`
   - Analytics billing endpoints: add `ModuleRequiredPermission('billing')`

3. Move `TenantFeaturesView` to `GET /api/v1/core/features/` (add to `core/urls.py`). Keep backward compat on old path with a 301 redirect.

4. Update `core.signals` — ensure new tenant signal already creates `emr` FeatureFlag as enabled. Add `analytics` flag (enabled if billing is enabled).

5. Tests: `TenantTestCase` for each module — flag off → 403, flag on → 200.

**Frontend tasks:**

6. Add `lib/features.ts`:
   ```typescript
   export async function getActiveModules(): Promise<string[]> {
     const token = getAccessToken();
     if (!token) return [];
     const res = await fetch('/api/v1/core/features/', {
       headers: { Authorization: `Bearer ${token}` },
     });
     if (!res.ok) return [];
     const data = await res.json();
     return data.active_modules ?? [];
   }
   ```

7. Add `hooks/useHasModule.ts` — calls `getActiveModules()`, caches in `sessionStorage` with 5-min TTL. **Error behavior: fail-open.** If the fetch fails or times out (>2s), fall back to showing all nav items (never lock the user out due to a network error). Render nav with `activeModules?.includes('billing')` null-coalescing — while the initial fetch is in flight, show all items (no skeleton, no flash). No layout shift.

8. In `DashboardShell.tsx` — conditionally render Billing, Farmácia, Analytics nav links based on `useHasModule()`.

**Migrations:** One `RunPython` migration is required. `FeatureFlag` rows do not currently exist for any tenant (the existing signal only fires on `Subscription` creation, and no subscriptions exist). Without this migration, deploying S-039 will immediately 403 all existing tenants on billing and pharmacy endpoints.

   Migration: `core/0XXX_backfill_feature_flags.py` — `RunPython` that iterates all tenants, reads their `Subscription.active_modules` (or defaults to `['emr']` if no subscription), and creates `FeatureFlag` rows for each module. Run atomically.

   Also update `core/signals.py`: add `post_save` on `Tenant` to create `emr` FeatureFlag for every new tenant on creation (even before a Subscription is created).

---

### S-040 — Platform Admin Subscription API

**Goal:** Vitali operator can manage plans and subscriptions via API. Creating a subscription for a tenant activates the specified modules.

**Acceptance criteria:**
- `GET/POST /api/v1/platform/plans/` — list/create plans (platform admin only)
- `GET/PATCH /api/v1/platform/plans/{id}/` — retrieve/update plan
- `GET/POST /api/v1/platform/subscriptions/` — list/create subscriptions
- `GET/PATCH /api/v1/platform/subscriptions/{id}/` — retrieve/update, includes `active_modules` field
- `POST /api/v1/platform/subscriptions/{id}/activate-module/` — activates a module: creates/updates `FeatureFlag` in the tenant's schema
- `POST /api/v1/platform/subscriptions/{id}/deactivate-module/` — deactivates a module
- All platform endpoints require `is_superuser=True` via `IsPlatformAdmin` permission class (clinic owners never hold superuser)
- Creating a subscription auto-enables the plan's `is_included=True` modules via signal

**Backend tasks:**

1. Create `backend/apps/core/serializers_platform.py` (or add to `serializers.py`):
   - `PlanSerializer` — Plan CRUD
   - `PlanModuleSerializer` — nested in Plan
   - `SubscriptionSerializer` — includes `active_modules`, `tenant_id`, `plan_id`

2. Create `PlanViewSet` and `SubscriptionViewSet` in `core/views.py` (or `views_platform.py`):
   - Both gated with `IsPlatformAdmin` (checks `user.is_superuser` — clinic owners never have this flag; see Taste Decision A resolution)
   - `SubscriptionViewSet` includes `@action` for `activate_module` and `deactivate_module`
   - `activate_module`: `FeatureFlag.objects.update_or_create(tenant=subscription.tenant, module_key=module_key, defaults={'is_enabled': True})` — **no `tenant_context()` needed; `FeatureFlag` is a public-schema table in `SHARED_APPS`**
   - `deactivate_module`: same, `defaults={'is_enabled': False}`

3. Wire to `core/urls_public.py`:
   ```python
   path("platform/plans/", PlanListCreateView.as_view()),
   path("platform/plans/<uuid:pk>/", PlanDetailView.as_view()),
   path("platform/subscriptions/", SubscriptionListCreateView.as_view()),
   path("platform/subscriptions/<uuid:pk>/", SubscriptionDetailView.as_view()),
   path("platform/subscriptions/<uuid:pk>/activate-module/", ActivateModuleView.as_view()),
   path("platform/subscriptions/<uuid:pk>/deactivate-module/", DeactivateModuleView.as_view()),
   ```

4. Signal: `post_save` on `Subscription` — when created, iterate `plan.modules.filter(is_included=True)` and `FeatureFlag.objects.update_or_create(tenant=subscription.tenant, module_key=module.module_key, defaults={'is_enabled': True})` — **no schema switching; FeatureFlag is public-schema.**

5. Tests: `TenantTestCase` with staff user — full CRUD + activate/deactivate module flow, verify `FeatureFlag.objects.filter(tenant=tenant, module_key=module_key, is_enabled=True).exists()` (public schema query, no schema switching needed).

---

### S-041 — Tenant Subscription Status Page

**Goal:** Tenant admin can see their current plan, active modules, and monthly price.

**Acceptance criteria:**
- `GET /api/v1/core/subscription/` returns the tenant's current subscription, plan name, active modules, monthly price, status, and period dates
- New page at `/configuracoes/assinatura` in the frontend
- Shows: plan name, status badge (Ativo/Em atraso/Cancelado), active modules as chips, monthly price, next billing date
- If no subscription: shows "Nenhuma assinatura ativa. Entre em contato com o suporte."
- Accessible from the user menu / settings nav

**Backend tasks:**

1. Add `TenantSubscriptionView` to `core/views.py`:
   - `GET /api/v1/core/subscription/`
   - Reads `Subscription.objects.using("default").filter(tenant=request.tenant).first()`
   - Returns serialized subscription or 404 with human message
   - Auth: `IsAuthenticated`, no special role requirement (any user can see their plan)

2. Wire to `core/urls.py`.

3. Test: TenantTestCase — GET returns subscription for tenant, 404 if none.

**Frontend tasks:**

4. New page: `frontend/app/(dashboard)/configuracoes/assinatura/page.tsx`
   - Fetches `/api/v1/core/subscription/`
   - **Information hierarchy (top to bottom):** (1) Status badge is the dominant visual — large, top-right. Plan name is top-left. Status colors: Ativo=green, Em atraso=red, Cancelado=gray. Status badge always shows text label + color (never color alone — WCAG AA). (2) KPI grid below: `grid md:grid-cols-2 gap-6` — Card 1: Monthly price (text-2xl blue) + next billing date subtitle. Card 2: Active modules header + chips. (3) CTA at bottom.
   - Module chips: `inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-green-100 text-green-700` with `✓` checkmark icon (14px). NOT clickable. Horizontal row, gap-2, wraps on overflow.
   - If status is "Em atraso": show warning banner below status badge: "Sua assinatura está em atraso." + context-aware CTA "Regularizar pagamento" (opens Calendly). If status is "Ativo": CTA is "Precisa de um módulo adicional? Agendar conversa →" (Calendly link, not raw email) — opens in new tab.
   - If no subscription (404): full-page empty state — `AlertCircle` icon + "Nenhuma assinatura ativa" + "Agendar conversa →" Calendly link.
   - **Mobile (sm):** full-width stacked layout — plan name + status at top, price + date below, chips below those. Use `grid md:grid-cols-2`.


5. Add "Configurações" nav item to `DashboardShell.tsx` (gear icon, links to `/configuracoes/assinatura`). Show only for `admin` role.

---

### S-042 — Purchase Orders (basic)

**Goal:** Farmacêuticos can create POs for suppliers, receive goods, and have stock updated automatically.

**Acceptance criteria:**
- `Supplier` model: name, CNPJ, contact, is_active
- `PurchaseOrder` model: supplier, status (draft/sent/partial/received/cancelled), expected_date, notes
- `PurchaseOrderItem` model: PO, drug OR material (generic FK or separate FKs), quantity_ordered, quantity_received, unit_price
- `POST /api/v1/pharmacy/purchase-orders/` — create PO draft
- `PATCH /api/v1/pharmacy/purchase-orders/{id}/` — update PO (add items, change status)
- `POST /api/v1/pharmacy/purchase-orders/{id}/receive/` — receive items: creates `StockMovement(movement_type='entry')` for each received item, adds a new `StockItem` lot if drug/lot doesn't exist
- Receiving is partial: `quantity_received` can be < `quantity_ordered`; PO status → `partial` or `received`
- Auth: `pharmacy.stock_manage` for all PO endpoints
- Frontend: `/farmacia/compras/` page — PO list; `/farmacia/compras/nova/` — create PO; `/farmacia/compras/[id]/` — PO detail with receive action

**Backend tasks:**

1. Models in `backend/apps/pharmacy/models.py`:
   ```python
   class Supplier(models.Model):
       name = CharField(max_length=200)
       cnpj = CharField(max_length=18, blank=True)
       contact_name = CharField(max_length=100, blank=True)
       contact_email = EmailField(blank=True)
       contact_phone = CharField(max_length=20, blank=True)
       is_active = BooleanField(default=True)

   class PurchaseOrder(models.Model):
       class Status(TextChoices):
           DRAFT = 'draft', 'Rascunho'
           SENT = 'sent', 'Enviado'
           PARTIAL = 'partial', 'Parcialmente recebido'
           RECEIVED = 'received', 'Recebido'
           CANCELLED = 'cancelled', 'Cancelado'

       supplier = ForeignKey(Supplier, on_delete=PROTECT)
       status = CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
       expected_date = DateField(null=True, blank=True)
       notes = TextField(blank=True)
       created_by = ForeignKey('core.User', on_delete=PROTECT, null=True)
       created_at = DateTimeField(auto_now_add=True)
       updated_at = DateTimeField(auto_now=True)

   class PurchaseOrderItem(models.Model):
       po = ForeignKey(PurchaseOrder, on_delete=CASCADE, related_name='items')
       drug = ForeignKey(Drug, on_delete=PROTECT, null=True, blank=True)
       material = ForeignKey(Material, on_delete=PROTECT, null=True, blank=True)
       quantity_ordered = DecimalField(max_digits=12, decimal_places=3)
       quantity_received = DecimalField(max_digits=12, decimal_places=3, default=0)
       unit_price = DecimalField(max_digits=10, decimal_places=2)

       class Meta:
           constraints = [
               CheckConstraint(check=Q(drug__isnull=False) | Q(material__isnull=False),
                               name='po_item_must_have_drug_or_material'),
               CheckConstraint(check=~Q(drug__isnull=False, material__isnull=False),
                               name='po_item_not_both'),
           ]
   ```

   Add to `StockItem.Meta` (existing model — new migration):
   ```python
   class Meta:
       unique_together = [
           ('drug', 'lot_number', 'expiry_date'),
           ('material', 'lot_number', 'expiry_date'),
       ]
   ```

2. Migrations:
   - `pharmacy/0005_supplier_purchaseorder.py` — new Supplier, PurchaseOrder, PurchaseOrderItem models
   - `pharmacy/0006_stockitem_unique_lot.py` — `unique_together` constraint on StockItem (drug/material + lot_number + expiry_date)

3. Add `'purchase_order_receiving'` to `StockMovement.MOVEMENT_TYPES`. **No separate migration needed — `choices` on a `CharField` are application-layer only in Django/PostgreSQL (no `CHECK` constraint in `Meta`). The change lives in the model class only.**

4. Serializers + ViewSets in `pharmacy/serializers.py` / `pharmacy/views.py`:
   - `SupplierViewSet` — CRUD, `pharmacy.stock_manage`
   - `PurchaseOrderViewSet` — CRUD + `@action` `receive`
   - `PurchaseOrderItemSerializer.validate()` — must enforce the XOR constraint at the application layer (not just DB): raise `serializers.ValidationError` if both `drug` and `material` are set, or if neither is set. Without this, constraint violations hit the DB and produce 500s, not 400s.
   - `receive` action: `@transaction.atomic` — for each item: `PurchaseOrderItem.objects.select_for_update().get(pk=item_id)` (lock the row to prevent concurrent race), compute delta, create `StockMovement(movement_type='purchase_order_receiving')`, update `quantity_received`, update PO status
   - StockItem lookup: use `get_or_create(drug=drug, lot_number=lot, expiry_date=expiry)` — `expiry_date` is the disambiguator (required field on receive form). DB `unique_together` on `(drug, lot_number, expiry_date)` prevents duplicates at the constraint level (see Taste Decision B resolution).

6. Wire to `pharmacy/urls.py`

7. Tests: PO creation, item addition, receive full/partial, verify StockMovements created, verify StockItem quantity updated atomically.

**Frontend tasks:**

8. `/farmacia/compras/page.tsx` — PO list (status filter, supplier filter, clickable rows). Filters: horizontal bar above table — Supplier dropdown + Status multi-select, real-time filter (no Apply button). Table columns: `Supplier | Expected Date | Item Count | Status Badge | Last Updated`. Status badge semantic colors: Draft=gray, Sent=blue, Partial=yellow, Received=green, Cancelled=red (DESIGN.md section 2 recipe). **Mobile (sm): transitions to card layout** — each PO is a card showing supplier name (bold), status badge, expected date, item count. Filters remain dropdowns above cards.
9. `/farmacia/compras/nova/page.tsx` — create PO form (supplier search dropdown, add items table with drug search)
10. `/farmacia/compras/[id]/page.tsx` — PO detail (items table with received quantities, "Registrar Recebimento" action button). **Interaction design required:** When the farmacêutico clicks "Registrar Recebimento": button disables + shows `Loader2` spinner (16px) inside. If request succeeds: show 4-second success toast "Recebimento registrado. Estoque atualizado." with a link to the drug's stock detail; reload page. If request fails with validation errors: show inline error banner at top of items table (`role="alert" aria-live="polite"`) with the specific message; button re-enables. If `[DEMO]` prefix detected in error response, show user-friendly "Demo mode" banner instead of raw JSON.

    **Mobile layout (sm):** Items table transitions to card-based list — each item card shows drug/material name, quantity ordered/received, unit price, and receive quantity input. "Registrar Recebimento" button spans full width at bottom. On desktop (md+): standard table.
11. Add "Compras" sub-nav under Farmácia in `DashboardShell.tsx`

---

### S-043 — Pilot Readiness

**Goal:** Demo-ready system — realistic data for investor demos, read-only mode for live demos, and onboarding steps for new clinics.

**Acceptance criteria:**
- `python manage.py seed_demo_data --tenant=<schema>` populates: 10 patients, 20 appointments, 8 encounters with SOAP notes, 5 guides (3 paid, 2 glosa), 1 batch, 50 stock items, 3 POs (received)
- Demo mode: `DEMO_MODE=true` in env → all `POST/PATCH/PUT/DELETE` requests return `{"detail": "This is a demo environment — write operations are disabled."}` with 403
- Onboarding checklist: `GET /api/v1/core/onboarding/` returns `{"steps": [{"id": "first_patient", "label": "Cadastrar primeiro paciente", "done": true}, ...]}` — checks whether each key entity type has been created
- Frontend onboarding widget: small callout on the dashboard home if `steps.some(s => !s.done)` — shows "3 de 5 passos concluídos" with a list
- Onboarding steps: first_patient, first_appointment, first_encounter, first_guide, first_stock_item

**Backend tasks:**

1. `backend/apps/core/management/commands/seed_demo_data.py`:
   - Uses `--tenant=<schema>` argument
   - Enters `tenant_context(tenant)`
   - Creates realistic Brazilian healthcare demo data using Faker with pt_BR locale
   - Idempotent: use sentinel check — `Patient.objects.filter(full_name__startswith='[DEMO]').exists()`. If True, skip and print "Demo data already present." Do NOT use `Patient.objects.count()` — a real tenant with 10 patients would trigger seed, corrupting their data.

2. Demo mode middleware in `core/middleware.py`:
   ```python
   DEMO_MODE_WHITELIST = (
       '/api/v1/auth/',   # login, token refresh, logout — must work in demo
   )

   class DemoModeMiddleware:
       def __call__(self, request):
           if settings.DEMO_MODE and request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
               if any(request.path.startswith(prefix) for prefix in DEMO_MODE_WHITELIST):
                   return self.get_response(request)  # auth endpoints always pass
               import logging
               logging.getLogger(__name__).warning(
                   "[DEMO_MODE] blocked %s %s for user=%s",
                   request.method, request.path, getattr(request.user, 'id', 'anon')
               )
               return JsonResponse(
                   {"detail": "[DEMO] This is a demo environment — write operations are disabled."},
                   status=403
               )
           return self.get_response(request)
   ```
   **Why whitelist auth paths:** Without this, `POST /api/v1/auth/refresh/` returns 403 in demo mode. The demo expires after the JWT access token TTL (~15 min) and the user is logged out with a confusing "demo environment" error.
   Wire to `MIDDLEWARE` list in `settings.py` (conditional: only if `DEMO_MODE=true`). The `[DEMO]` prefix in the response body distinguishes demo blocks from real auth errors. Add startup check in `apps.py` `ready()`: if `DEMO_MODE=true` and `ENVIRONMENT not in ('demo', 'staging')`, log `WARNING: DEMO_MODE is active in environment={ENVIRONMENT}. Verify this is intentional.`

3. `OnboardingView` in `core/views.py`:
   - Checks each step: `Patient.objects.exists()`, `Appointment.objects.exists()`, etc.
   - Returns ordered list of steps with `done` boolean and `action_url` for each (e.g., `/patients/new`, `/farmacia/estoque/new`)
   - Add to `core/urls.py`

4. Tests: seed_demo_data (runs without error, creates expected counts), onboarding (steps correctly reflect empty vs populated tenant).

**Frontend tasks:**

5. `OnboardingWidget` component: small callout on `/dashboard/page.tsx` (currently the home page) — renders if any step is incomplete. Shows progress bar + step list with checkmarks. Each incomplete step has a "Fazer agora →" CTA button that navigates to the creation form directly (not the list). "Cadastrar primeiro paciente" → `/patients/new`. "Criar primeiro guia" → `/billing/guides/new`. Not just a nav link.

---

## Test Plan

### Unit tests (backend)

| Test | File |
|---|---|
| `ModuleRequiredPermission` — flag off → 403 | `core/tests/test_permissions.py` |
| `ModuleRequiredPermission` — flag on → 200 | `core/tests/test_permissions.py` |
| `ModuleRequiredPermission` — superuser bypasses | `core/tests/test_permissions.py` |
| Billing endpoints — billing flag off → 403 | `billing/tests/test_module_gate.py` |
| Platform subscription CRUD | `core/tests/test_platform_api.py` |
| Activate/deactivate module — FeatureFlag created in tenant schema | `core/tests/test_platform_api.py` |
| Subscription auto-enables included modules on create | `core/tests/test_platform_api.py` |
| TenantSubscriptionView — returns subscription | `core/tests/test_subscription.py` |
| TenantSubscriptionView — 404 when no subscription | `core/tests/test_subscription.py` |
| PO creation, item add | `pharmacy/tests/test_purchase_orders.py` |
| PO receive full — creates StockMovement, updates quantity | `pharmacy/tests/test_purchase_orders.py` |
| PO receive partial — status → partial | `pharmacy/tests/test_purchase_orders.py` |
| PO receive atomic — if one item fails, none committed | `pharmacy/tests/test_purchase_orders.py` |
| seed_demo_data — creates expected counts, idempotent | `core/tests/test_seed_demo_data.py` |
| OnboardingView — empty tenant → all false | `core/tests/test_onboarding.py` |
| OnboardingView — with data → correct done flags | `core/tests/test_onboarding.py` |
| DemoModeMiddleware — POST blocked in demo mode | `core/tests/test_demo_mode.py` |
| DemoModeMiddleware — GET allowed in demo mode | `core/tests/test_demo_mode.py` |
| DemoModeMiddleware — POST /api/v1/auth/refresh/ allowed in demo mode (whitelist) | `core/tests/test_demo_mode.py` |
| `PurchaseOrderItemSerializer` — both drug and material set → 400 (not 500) | `pharmacy/tests/test_purchase_orders.py` |
| `PurchaseOrderItemSerializer` — neither drug nor material set → 400 | `pharmacy/tests/test_purchase_orders.py` |
| Pharmacy endpoints — pharmacy flag off → 403 | `pharmacy/tests/test_module_gate.py` |
| AI endpoints — ai_tuss flag off → 403 | `ai/tests/test_module_gate.py` |
| New tenant signal — emr FeatureFlag created on Tenant post_save | `core/tests/test_signals.py` |
| Backfill migration — existing tenant with Subscription gets correct flags | `core/tests/test_migrations.py` |

### Frontend smoke checks

- Billing nav hidden when billing module inactive
- `/farmacia/compras/` loads PO list
- PO receive form submits correctly
- Onboarding widget shows/hides based on steps
- `/configuracoes/assinatura` loads without errors

---

## Architecture Notes

**Module gating runs at the DRF permission layer** — not middleware. Middleware-level gating would block admin endpoints too. DRF `permission_classes` gives per-viewset control with proper 403 DRF responses (JSON, not HTML).

**PO receiving is atomic** — `@transaction.atomic` wrapper around the receive action. StockMovement is append-only (enforced by model's `save()`), so if any item fails, the whole transaction rolls back.

**Demo mode uses middleware, not a flag on each view** — centralized, zero chance of forgetting to check the flag in a new view.

**Subscription API lives in public schema** — `Plan`, `PlanModule`, `Subscription`, and `FeatureFlag` are all public-schema models (`SHARED_APPS`). The `activate_module` endpoint does NOT cross schemas and does NOT need `tenant_context()`. It simply writes `FeatureFlag(tenant=subscription.tenant, ...)` directly — the row lands in the public schema automatically. This is simpler than previously described.

**`StockItem` lot_number for PO receiving** — PO receiving creates stock with `lot_number=f"PO-{str(po.id)[:8]}"` if not provided (note: `str()` required — `UUID` objects don't support slice notation directly). The `get_or_create` lookup uses `(drug, lot_number, expiry_date)` as the key. `StockItem.Meta` adds `unique_together = [('drug', 'lot_number', 'expiry_date'), ('material', 'lot_number', 'expiry_date')]` — DB-level constraint prevents concurrent duplicates. One additional migration: `pharmacy/0006_stockitem_unique_lot.py`.

---

## Pricing (Must Be Defined Before Onboarding Any Clinic)

**REQUIRED before Sprint 11 ships:** At least one Plan row must be seeded. Leaving the Plans table empty and activating modules manually without a stated price makes subscription tracking meaningless. Propose:

| Plan | Price (R$/mês) | Included modules |
|---|---|---|
| Essencial | TBD | emr |
| Clínica | TBD | emr + billing + analytics |
| Plus | TBD | emr + billing + analytics + pharmacy + ai_tuss |

Actual prices to be decided by the founder before Sprint 11 PR is merged. A `seed_plans` management command should create these rows idempotently so any fresh install has a usable pricing structure.

---

## Open Risks (Not In Scope — Log for Sprint 12+)

| Risk | Impact | Owner |
|---|---|---|
| No DPA / LGPD data processing agreement | Blocks clinic sign | Legal/Founder |
| No SLA definition | Blocks clinic sign | Founder |
| No data migration / CSV import for patients | Blocks migration from existing system | Engineering |
| WhatsApp unscheduled — P0 gap per project brief | Blocks signing clinics in Brazil | Engineering (Sprint 12?) |
| ANVISA controlled substance compliance for PO receiving | Pharmacy pilot risk | Engineering (Sprint 12) |
| No backup visibility for tenant admin | Trust gap for clinic owner | Engineering |
| No audit log access for tenant admin (LGPD/CFM) | Compliance gap | Engineering |
| Self-service tenant registration not built | SaaS vs managed-service gap | Engineering |

---

## Decision Log

| Decision | Rationale |
|---|---|
| No self-service module activation | Payment integration (PagarMe/Stripe) is out of scope for pilot. Vitali team activates manually via API. This makes Sprint 11 a managed-service pilot, not full SaaS — acknowledged. |
| PO receiving creates StockItem if not exists | Simplest path: farmacêutico doesn't need to create the stock item before receiving. PO receiving is the natural first entry point. |
| Demo mode is middleware, not per-view | Zero risk of a new view forgetting to check. Works automatically for all future endpoints. Response prefixed with `[DEMO]` to distinguish from auth errors. |
| Onboarding steps are server-side checks | Avoids client-side tracking that could get out of sync. Server checks real DB state. |
| `analytics` module flag auto-enabled with billing | Analytics only has billing data. Gating them separately would confuse users — if you have billing, you have analytics. |
| ANVISA controlled substance PO compliance deferred | PO receiving does not currently validate controlled substance documentation requirements. This is a Sprint 12 concern. For Sprint 11 pilot, clinic must not use PO receiving for ANVISA class A/B/C items without a manual process. |
| S-042 Purchase Orders: KEEP in Sprint 11 | Pharmacy pilot needs the full stock entry loop. Manual adjustment is a workaround, not a workflow. Decision: founder confirmed keep. |
| WhatsApp: Schedule Sprint 12 | Commits to a concrete answer for pilot clinics asking "can patients book via WhatsApp?" Sprint 12 = WhatsApp engagement (Evolution API). |
| Pricing: Deferred to founder | Business decision not in scope for the technical plan. Founder will set prices before pilot onboarding. |

---

---

## Taste Decisions (RESOLVED)

### Taste Decision A — Platform Admin Auth: RESOLVED → `is_superuser`

**Decision:** Use `IsPlatformAdmin(BasePermission)` checking `user.is_superuser`. `is_staff` was too permissive — clinic owners could hold it for Django admin access. `is_superuser` is reserved for true Vitali platform operators. Named class (`IsPlatformAdmin`) documents the concept explicitly for future extension.

### Taste Decision B — `StockItem` Unique Constraint: RESOLVED → `unique_together` + migration

**Decision:** Add `unique_together = [('drug', 'lot_number', 'expiry_date'), ('material', 'lot_number', 'expiry_date')]` to `StockItem.Meta`. One new migration (`pharmacy/0006_stockitem_unique_lot.py`). DB-level constraint is the correct inventory design. Expiry date is required on the PO receive form.

---

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Success metric reframed from "30-min internal setup" to "first-time faturista operational in 30 min" | P5 (explicit) | Internal ops metric doesn't predict product success | Old metric |
| 2 | CEO | Onboarding widget items get CTA buttons to creation forms, not nav links | P1 (completeness) | Checklist without guided action is friction, not help | Nav-link-only approach |
| 3 | CEO | Subscription page shows Calendly link, not raw email | P5 (explicit) | "Email us" is the most 1995 feature in a 2026 SaaS product | Raw email address |
| 4 | CEO | Demo mode logs WARNING with [DEMO] prefix + startup env check | P3 (pragmatic) | Without prefix, demo 403s are indistinguishable from real auth errors | Silent blocking |
| 5 | CEO | Open Risks section added (DPA, SLA, WhatsApp, ANVISA, audit log, backup visibility) | P6 (bias toward action) | CEO review found 7 signing-blockers; logging them explicitly prevents them from being lost | Not documented |
| 6 | CEO | Pricing section added as TBD with `seed_plans` command | P1 (completeness) | Empty Plans table makes subscription UX meaningless at launch | All-TBD pricing deferred |
| 7 | PREMISE | S-042 Purchase Orders: KEEP | User confirmed | Pilot pharmacy loop requires PO receiving | Dropping to Sprint 12 |
| 8 | PREMISE | WhatsApp: Sprint 12 | User confirmed | P0 gap needs a committed date for pilot sales conversations | Open-ended deferral |
| 9 | PREMISE | Pricing: User-deferred | User decision | Business decision outside technical plan scope | Defining prices in plan |
| 10 | ENG | FeatureFlag is public-schema — removed all tenant_context() references from S-040 | P5 (explicit) | FeatureFlag is in SHARED_APPS; writing with tenant_context would cause ProgrammingError at runtime | Keeping cross-schema description |
| 11 | ENG | Data migration added to S-039 — backfill FeatureFlag rows for existing tenants | P1 (completeness) | Without this, day-1 deploy breaks every existing tenant on billing/pharmacy endpoints | "Migrations: None" |
| 12 | ENG | DemoModeMiddleware whitelists auth paths — token refresh allowed in demo mode | P3 (pragmatic) | Without whitelist, JWT expires after 15min and demo fails with misleading error | Blocking all POST including auth |
| 13 | ENG | seed_demo_data idempotency changed to sentinel-based ([DEMO] prefix) | P5 (explicit) | Count-based check corrupts real tenant data | Patient.objects.count() check |
| 14 | ENG | PurchaseOrderItemSerializer.validate() added — XOR constraint at app layer | P2 (DRY/explicit) | DB-level CheckConstraint produces 500; must raise 400 at serializer layer | Only DB enforcement |
| 15 | ENG | Added select_for_update() on PurchaseOrderItem in receive action | P3 (pragmatic) | Concurrent receives race on quantity_received without row lock | Relying on StockMovement locking alone |
| 16 | ENG | str(po.id)[:8] — added str() cast for UUID slice | P5 (explicit) | UUID objects don't support slice notation; would raise TypeError at runtime | po.id[:8] |
| 17 | ENG | Removed migration 0006 (MOVEMENT_TYPES choice is not a DB schema change) | P1 (completeness) | CharField choices are app-layer only; no-op migration adds noise | Creating 0006 |
| 18 | ENG/DESIGN | tenant_has_feature moved to utils.py — avoids circular import | P5 (explicit) | permissions.py importing from middleware.py → circular import at startup | import from middleware |
| 19 | DESIGN | PO receive form interaction design specified — button states, toast, error banner | P1 (completeness) | Without these specs, frontend ships with undefined behavior on submit | Unspecified states |
| 20 | DESIGN | Subscription page information hierarchy specified — status badge dominant top-right | P5 (explicit) | Inverted priority buried the most important signal (is my plan active?) | Flat list with no hierarchy |
| 21 | DESIGN | Module chips design specified (pill badge, DESIGN.md pattern, non-clickable) | P5 (explicit) | "Chips" without spec → 7 possible interpretations from the implementer | Generic "chips" |
| 22 | ENG/USER | Platform admin auth changed from is_staff → is_superuser via IsPlatformAdmin class | P5 (explicit) | is_staff can be granted to clinic owners for Django admin; is_superuser is strictly platform operators | is_staff + policy doc |
| 23 | ENG/USER | StockItem unique_together added on (drug/material, lot_number, expiry_date) + migration 0006 | P1 (completeness) | Without DB constraint, concurrent receives corrupt inventory; get_or_create raises MultipleObjectsReturned | No constraint + try/except |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | DONE — 6 auto-fixes, 3 premise gate decisions | Success metric, onboarding CTAs, demo mode prefix, Calendly, Open Risks, pricing |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | DONE — taste decisions A+B resolved | 1 CRITICAL (backfill migration), 5 HIGH, 8 MEDIUM auto-fixed; A→is_superuser, B→unique_together |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | DONE — 12 auto-fixes | 1 CRITICAL (PO receive form states), 5 HIGH (hierarchy, mobile, module chips) |

**AUTO-FIXED:** 21 items across all 3 reviews applied to plan.

**VERDICT: APPROVED — all taste decisions resolved. Ready to branch `feature/sprint11-commercialization`.**
