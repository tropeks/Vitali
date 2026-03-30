# Changelog

All notable changes to Vitali Health are documented here.

## [0.3.0] — 2026-03-30

### Added
- **Pharmacy app (Sprint 7):** Full pharmacy module — catalog, stock management, dispensation
  - **S-026 Drug & Material Catalog:** `Drug` model with ANVISA code, barcode, controlled-substance classification (ANVISA lists A1–C5), and soft-delete; `Material` model for non-drug hospital supplies; full CRUD REST API with search, permission-gated writes (`pharmacy.catalog_manage`)
  - **S-027 Stock Management:** `StockItem` (lot ledger) + `StockMovement` (append-only movement log); FEFO-ready lot ordering; `CheckConstraint(quantity >= 0)` at DB level; F()-based atomic quantity updates preventing race conditions; stock adjustment endpoint (`POST /pharmacy/stock/items/{id}/adjust/`) requiring `pharmacy.stock_manage`; `StockAlertsView` reading pre-computed expiry + low-stock alerts from Redis; Celery tasks (`check_expiry_alerts`, `check_min_stock_alerts`) writing tenant-scoped Redis keys
  - **S-028 Dispensation:** Atomic FEFO multi-lot dispensation (`POST /pharmacy/dispense/`) with `select_for_update()` on both `PrescriptionItem` (over-dispense guard) and stock lots; controlled-substance gate (`pharmacy.dispense_controlled`); mandatory notes for controlled drugs; `Dispensation` + `DispensationLot` models; stock availability query endpoint
  - **Prescription items (EMR):** `Prescription` + `PrescriptionItem` models with sign/cancel lifecycle; `MinValueValidator(Decimal('0.001'))` on item quantity; serializer blocks adding items to signed prescriptions; REST API under `/api/v1/` with permission guards
  - **Pharmacy frontend (Sprint 7):** 5 pages under `/farmacia/`
    - Catalog page (drug + material tabs, search, inline creation form, clickable rows)
    - Drug detail page (view/edit/deactivate, controlled-class badge)
    - Material detail page (view/edit/deactivate)
    - Stock list page (KPI alert cards, filters, entry form with drug search, clickable rows)
    - Stock item detail page (quantity/min/expiry KPI cards, adjustment form, movement history)
  - **Pharmacy nav link** in `DashboardShell`

### Fixed
- **Stock adjust permission gap:** `adjust` action on `StockItemViewSet` previously fell through to `pharmacy.read`; now correctly requires `pharmacy.stock_manage`
- **PrescriptionItem `MinValueValidator`:** Changed from string `'0.001'` to `Decimal('0.001')` to avoid `TypeError` on decimal field comparison

### Changed
- API version bumped from `0.2.0` → `0.3.0`

---

## [0.2.0] — 2026-03-30

### Added
- **Billing app (Sprint 6a):** Full TISS/TUSS billing foundation
  - `TISSGuide` model with atomic sequential guide number generation (`YYYYMM + 6-digit seq`)
  - `TISSBatch` model with open/close lifecycle and double-submit protection
  - `Glosa` model with appeal workflow
  - `InsuranceProvider` and `PriceTable` models
  - TISS XML generation engine with ANS XSD validation
  - TISS retorno XML parser (updates guide statuses and creates Glosa records)
  - Role-based permission guard (`IsFaturistaOrAdmin`) on all billing endpoints
  - Full REST API: guides, batches, glosas, providers, price tables, TUSS code search
- **TUSSCode model:** Shared-schema TUSS procedure code table with full-text search
  - Management command `import_tuss` for loading ANS TUSS CSV
  - GIN index on `search_vector` for fast combobox queries
- **PatientInsurance model (EMR):** Links patients to insurance providers with card numbers
- **Billing frontend (Sprint 6b):** 9 pages under `/billing/`
  - Overview dashboard with KPI cards, recent guides, open batches
  - Guides list with status/search filters
  - Guide creation form (encounter, patient, provider, TISS items)
  - Guide detail with submit action and glosas section
  - Batches list with new batch modal
  - Batch detail with close/export/upload retorno actions
  - Glosas management with appeal filing
  - Price tables management
  - Billing nav link in `DashboardShell`

### Fixed
- **Auth token access (ISSUE-001):** Dashboard and encounter pages read `localStorage.getItem('access_token')` but login only sets an `httpOnly` cookie invisible to JS. Fixed by adding a non-httpOnly `access_token_js` mirror cookie in login/refresh/logout routes and centralizing token access in `lib/auth.ts:getAccessToken()`.
- **Auth tests:** `AuthTestCase` ran in public schema (Django `TestCase`), causing 404s on tenant auth endpoints. Migrated to `TenantTestCase` with `SERVER_NAME` routing and `cache.clear()` in setUp.
- **XML XXE vulnerability:** `lxml.etree.fromstring()` called without parser options in retorno parser and XSD validator. Fixed by passing `XMLParser(resolve_entities=False, no_network=True)`.

### Changed
- API version bumped from `0.1.0` → `0.2.0`
- `backend/requirements/base.txt`: added `jinja2>=3.1` (TISS XML templates), `lxml>=5` (XSD validation)

## [0.1.0] — 2026-03-01

- Sprint 1–5: Multi-tenant foundation, EMR core, authentication, patient management, appointments, encounters, SOAP notes, waiting room
