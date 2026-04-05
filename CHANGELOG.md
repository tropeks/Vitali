# Changelog

All notable changes to Vitali Health are documented here.

## [0.7.0] — 2026-04-05

### Added
- **WhatsApp Patient Engagement (Sprint 12, S-032/033/034/035):** Full WhatsApp appointment scheduling via conversational FSM, LGPD-compliant opt-in/opt-out, 24h and 2h automated reminders, post-visit satisfaction surveys, and receptionist conversation history panel.
  - **S-032 WhatsApp Webhook + LGPD Consent:** `WebhookView` with HMAC-SHA256 validation (fail-closed when secret unset), per-contact rate limiting (20 msg/min, atomic `cache.incr`), `WhatsAppContact` model with opt-in lifecycle (`do_opt_in` / `do_opt_out`), `MessageLog` audit trail with CPF fully masked (`***.***.***-**`). Evolution API integration via `EvolutionAPIGateway`. REST API: `GET/POST /api/v1/whatsapp/contacts/`, `GET /api/v1/whatsapp/message-logs/`, `GET /api/v1/whatsapp/health/`, `POST /api/v1/whatsapp/setup-webhook/`. 6 test files.
  - **S-033 Appointment Scheduling FSM:** 13-state `ConversationFSM` covering LGPD consent → specialty/professional/date/time selection → confirmation → booking. Intent detection for 30+ PT-BR phrases. Max 3 unrecognized inputs before FALLBACK_HUMAN. `select_for_update()` on Professional row prevents double-booking of empty slots. Session deleted after booking (CPF/PII gone). `slot_service.py` generates available slots from `ScheduleConfig` (working hours, lunch break, slot duration) minus booked appointments. 
  - **S-034 Appointment Reminders:** Celery tasks `send_appointment_reminders` (24h + 2h windows, every 15 min) and `mark_no_shows` (hourly) with `select_for_update(skip_locked=True)` inside `transaction.atomic()`. `ScheduledReminder` model with `unique_together` guard prevents duplicate sends.
  - **S-035 Satisfaction Surveys + Settings UI:** `send_satisfaction_surveys` task sends post-visit survey 2h after appointment completion. Frontend: `/configuracoes/whatsapp` settings page (QR code scan flow, connection status, conversation history with contact list + message thread), appointment badge in `/appointments` page.

### Fixed
- **WhatsApp booking flow (6 critical pre-ship bugs):** `_parse_date_selection` returned raw int instead of ISO date string; `_get_specialties` used Professional PK as specialty menu ID; `_get_professionals` had same PK-vs-menu-index bug; `select_for_update()` called outside `transaction.atomic()` in tasks (TransactionManagementError); `"2"` in global INTENT_MAP triggered opt-out from every numeric menu state; `session.save()` called after `session.delete()` on booking confirmation (IntegrityError). All fixed.
- **Security (3 pre-ship bugs):** Webhook fail-open when `WHATSAPP_WEBHOOK_SECRET` unset (now fail-closed); `SetupWebhookView` accepted client-supplied webhook URL (SSRF, now server-side only); `_log_message` CPF mask exposed last digit via `m.group()[-1]` (now fully masked).
- **Rate limiter race condition:** Non-atomic `cache.get`/`cache.set` in `_check_rate_limit` replaced with atomic `cache.incr()`.
- **Pagination missing:** `WhatsAppContactViewSet` had no pagination (50k-row response risk); added `MessageLogPagination`.

## [0.6.0] — 2026-04-05

### Added
- **Commercialization Layer (Sprint 11):** Module gating, subscription management, purchase orders, and pilot readiness — the infrastructure for a real revenue model
  - **S-039 Module Permission Layer:** `ModuleRequiredPermission` DRF permission class gates every billing, pharmacy, analytics, and AI endpoint by tenant `FeatureFlag`. Frontend `useHasModule()` hook with 5-minute `sessionStorage` TTL hides nav items for inactive modules (fail-open — all items visible until fetch completes, no layout shift). Applied to 15 ViewSets/Views across billing, analytics, pharmacy, and AI apps. `ALLOWED_MODULE_KEYS` constant in `core/constants.py` as the single source of truth. 9 tests.
  - **S-040 Platform Admin Subscription API:** REST API for `Plan`, `PlanModule`, and `Subscription` in the public schema — the Vitali operator control plane. `IsPlatformAdmin` permission (superuser only). `ActivateModuleView` and `DeactivateModuleView` with `select_for_update()` TOCTOU protection. PATCH on `Subscription.active_modules` uses double-lock pattern to sync `FeatureFlag` rows atomically. `POST /api/v1/platform/subscriptions/{id}/activate-module/` and `deactivate-module/`. 7 tests.
  - **S-041 Tenant Subscription Status Page:** `GET /api/v1/subscription/` returns current plan, active modules, and pricing for the tenant admin. New `/configuracoes/assinatura` page — shows plan name, active module badges, and renewal date. "Configurações" nav item (gear icon, admin-only). Graceful 404 empty-state when no subscription is configured.
  - **S-042 Purchase Orders:** `Supplier`, `PurchaseOrder`, `PurchaseOrderItem` models. Full PO lifecycle: create → send → receive (partial or full). `POST /pharmacy/purchase-orders/{id}/receive/` creates `StockMovements` and updates `StockItem.quantity` atomically via `F()` expressions with `select_for_update()`. New `'purchase_order_receiving'` movement type added to `StockMovement.MOVEMENT_TYPES`. Frontend: PO list (`/farmacia/compras`), PO detail (`/farmacia/compras/{id}`), create PO form (`/farmacia/compras/nova`) with supplier autocomplete and drug/material search. Status badges match DESIGN.md semantic color system. 9 tests.
  - **S-043 Pilot Readiness:** `seed_demo_data` management command populates a tenant with realistic demo data. `DemoModeMiddleware` wraps all write endpoints in 403 when `DEMO_MODE=true` (auth and platform admin paths whitelisted). `OnboardingView` (`GET /api/v1/onboarding/`) returns step completion state. `OnboardingWidget` renders on the dashboard when any step is incomplete — progress bar + step list with "Fazer agora →" CTAs. 6 tests.

### Fixed
- **Dashboard CORS failure:** Analytics fetches used `http://localhost:8000` directly — CORS blocked in browser. Now uses relative `/api/v1/analytics` path through the Next.js catch-all proxy.
- **OnboardingWidget 404:** Widget called `/api/v1/core/onboarding/` (wrong URL). Corrected to `/api/v1/onboarding/` per `core/urls.py` routing.
- **OnboardingWidget hidden on analytics error:** Error state rendered without `<OnboardingWidget />`. Fixed — widget now shows even when analytics returns an error.
- **Analytics 403 not cleared:** 403 response (analytics module inactive) left `error` state set, causing a red error banner. Fixed — `setError(null)` added before the early return.
- **Next.js proxy trailing-slash loss:** `next.config.mjs` rewrites stripped trailing slashes before forwarding, causing Django DRF 404s. Replaced with a catch-all proxy route (`app/api/[...path]/route.ts`) that preserves trailing slashes explicitly.
- **Docker-internal tenant routing:** Server-side `fetch()` from Next.js to Django used the container hostname (`django:8000`) as the `Host` header, which didn't match any `django-tenants` `Domain` row. Fixed by forwarding `X-Forwarded-Host` (stripped port) and enabling `USE_X_FORWARDED_HOST=True` in Django settings.

## [0.5.0] — 2026-04-02

### Added
- **Billing Intelligence Dashboard (Sprint 10):** Full analytics layer for billing — 5 API endpoints, 6 frontend components, and a TUSS staleness monitor
  - **S-035 Billing Analytics API:** 5 aggregate endpoints — `GET /api/v1/analytics/billing/overview/` (KPI cards: denial rate, total billed/collected/denied for current month); `GET /api/v1/analytics/billing/monthly-revenue/` (monthly revenue trend grouped by `competency` field, not `created_at`); `GET /api/v1/analytics/billing/denial-by-insurer/` (top insurers by denied value, ≥10 guide volume floor); `GET /api/v1/analytics/billing/batch-throughput/` (created vs closed batches per month, two-query merge); `GET /api/v1/analytics/billing/glosa-accuracy/` (AI prediction precision and recall per insurer); all protected with `IsAuthenticated`; 35 tests covering edge cases including appeal-status in denial totals, draft exclusion from denial rate denominator, cross-month batch merge, precision=null guard
  - **S-036 Billing Intelligence Page:** New `/billing/analytics` frontend page — sidebar "Análise" nav item (BarChart2 icon); KPI cards row (locked to current month, 2×4 responsive grid); denial-by-insurer horizontal bar chart with click-to-filter navigation to `/billing/guides`; revenue trend stacked area chart ("Não Glosado" vs "Glosado"); batch throughput line chart; Glosa AI Accuracy table with cold-start onboarding copy and warming-up progress indicators; 3m/6m/12m period toggle (default 6m, affects charts only); per-section independent error banners with retry; animate-pulse skeletons during load; keyboard-accessible chart bars
  - **S-037 Glosa Prediction Accuracy Tracker:** Integrated into S-035/S-036 — precision = true_positives / predicted_high; recall = true_positives / was_denied; precision=null when no high-risk predictions; unresolved predictions (was_denied=None) excluded from denominator
  - **S-038 TUSS Staleness Monitor:** `check_tuss_staleness` Celery task — three thresholds: <14d = fresh (no log), 14–29d = INFO "ageing", ≥30d = WARNING "stale"; queries `TUSSSyncLog` from public schema; DB errors caught and returned gracefully; registered via data migration `apps.ai.0004` using `PeriodicTask.get_or_create` (idempotent); `cleanup_orphaned_glosa_predictions` also registered in the same migration

## [0.4.0] — 2026-03-31

### Added
- **AI TUSS Auto-Coding (Sprint 8):** AI-assisted procedure code suggestion for faturistas — `apps/ai` Django app with full LLM integration pipeline
  - **S-030 LLM Integration Layer:** `LLMGateway` abstract class + `ClaudeGateway` (claude-haiku-4-5-20251001); `AIPromptTemplate` model with `(name, version)` unique constraint for safe versioning; `AIUsageLog` append-only call log with event types (llm_call, cache_hit, zero_result, validation_dropout, degraded); per-tenant Redis rate limiter (default 100 calls/hour, fail-open); Redis circuit breaker (3 failures/60s → 5min cooldown, fail-open); `run_llm_task` Celery task; admin interface for templates and logs
  - **S-031 TUSS Suggestion API:** Two-stage retrieval pipeline: GIN search_vector (Portuguese FTS) → trigram fallback → Claude re-ranking; DB validation gate blocks hallucinated codes; `TUSSAISuggestion` model records every suggestion shown with acceptance tracking; 24h tenant-scoped Redis cache (SHA-256 key, prompt-version-aware); `POST /api/v1/ai/tuss-suggest/` returns up to 3 ranked suggestions with `tuss_code_id`, `suggestion_id`, and `degraded`/`cached` flags; `POST /api/v1/ai/tuss-suggest/feedback/` records faturista accept/reject; `GET /api/v1/ai/usage/` admin monthly usage dashboard (tokens in/out, latency, acceptance rate); gated by `FEATURE_AI_TUSS` feature flag (default off)
  - **Frontend `TUSSSuggestionInline`:** 6-state pill component (idle/loading/suggestions/empty/degraded/idle-after-select) wired into guide creation form; 600ms debounce, per-row AbortController for race-safe fetches; overwrite confirmation dialog; fires acceptance feedback on pill selection; clears after selection
  - **Security hardening:** `guide_type` allowlist validation in serializer; curly-brace stripping on user inputs before LLM prompt `.format()`; JSON parse errors do not trip circuit breaker (only API transport failures do); prompt injection guards on both description and guide_type fields

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
- **Prescription status never updated after dispensation:** `_dispense_fefo()` completed dispensation without updating `Prescription.status`; now locks the prescription row and sets `partially_dispensed` or `dispensed` correctly. Regression tests added.
- **`StockAlertsView` silent Redis failure:** On cache miss/failure the view returned an empty list with 200 and no indication of failure; now returns `cache_available: false` so the frontend can show a warning.
- **`timezone.timedelta` crash in Celery tasks:** `django.utils.timezone` has no `timedelta` attribute; `check_expiry_alerts` and `check_min_stock_alerts` crashed on every invocation. Fixed by importing `from datetime import timedelta` directly.
- **Duplicate drugs in search results:** Queryset union (`|`) on `name` + `generic_name` returned duplicates for drugs matching both fields. Fixed using a single `Q()` OR filter.
- **Audit logged before save in `perform_destroy`:** Audit record was written before `save()` completed; if save raised, a phantom audit entry would exist. Fixed: log after save.
- **Missing auth headers on all pharmacy frontend pages:** All 19 fetch calls across 6 pharmacy pages (`catalog`, `drugs/[id]`, `materials/[id]`, `stock`, `stock/[id]`, `dispense`) were missing `Authorization: Bearer <token>` headers, causing 401s in production. Fixed.
- **Null token sending `Authorization: Bearer null`:** `getAccessToken()` returns `null` when session is expired; string interpolation produced a literally invalid header. Added `!token` guards to all write handlers — they now surface "Sessão expirada" instead of silently failing.
- **`materials/[id]` DELETE always navigated on failure:** `router.push()` was called unconditionally after DELETE; now checks for `res.ok || res.status === 204` before navigating.
- **`filterExpiring` included null-expiry items:** When "expiring in 30 days" filter was active, items with no expiry date appeared in results. Fixed: null-expiry items are now hidden when filter is active.

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
