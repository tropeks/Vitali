# Changelog

All notable changes to Vitali Health are documented here.

## [1.0.0] — 2026-04-22

### Added
- **Clinical AI Layer + MFA (Sprint 15, S-062–S-066):** First Phase 2 release. AI becomes a clinical co-pilot — prescription safety checks, CID-10 suggestions, SOAP transcription — and MFA protects staff accounts for the live pilot. Version bump to v1.0.0 marks the first production-grade release.
  - **S-062 Multi-Factor Authentication (TOTP):** `django-otp`, `pyotp`, `qrcode[pil]` added. `TOTPDevice` migration (`core/0010_totpdevice.py`). `MFARequiredMiddleware` enforces `mfa_verified` JWT claim on staff/superuser requests. Endpoints: `POST /auth/mfa/setup/` (QR URI + base32), `POST /auth/mfa/verify/` (backup codes shown once), `POST /auth/mfa/login/` (second-step JWT), `POST /auth/mfa/disable/` (platform admin). `MFA_GRACE_PERIOD_DAYS` env var (default 30). Frontend: `/profile/security` (enrollment + QR + backup codes download), `/auth/mfa` (6-digit auto-submit), MFA status badge on settings.
  - **S-063 AI Prescription Safety Net:** `PrescriptionSafetyChecker` service (Claude Haiku) — drug-drug interactions, dose validation, allergy cross-check, contraindications for encounter diagnoses. `AISafetyAlert` model + migration (`emr/0010_aisafetyalert.py`). Signal `post_save` on `PrescriptionItem` → `check_prescription_safety` Celery task. Redis cache 1h by `sha256(drug + other_drugs_sorted + allergies_sorted)`. Feature flag `ai_prescription_safety`. Endpoints: `POST /emr/prescriptions/{id}/items/{item_id}/safety-check/`, `POST .../acknowledge-alert/` (override logged to AuditLog). Frontend: `SafetyBadge`, `SafetyAlertModal`, `PrescriptionBuilder` polls for 10s with amber → green/yellow/red state.
  - **S-064 AI CID-10 Suggester:** `CID10Suggester` service — top-3 ICD-10 suggestions with confidence, validated against local `CID10Code` table (rejects hallucinated codes). `AICIDSuggestion` model tracks accepted/rejected outcomes. `CID10Code` migration (`core/0008_cid10code.py`). Redis cache 24h by `sha256(normalized_text)`. Feature flag `ai_cid10_suggest`. Endpoints: `POST /emr/encounters/{id}/cid10-suggest/`, `POST .../cid10-accept/`. Frontend: `CID10Suggest` component with 1.5s debounce + 3 suggestion chips, wired into `SOAPEditor`.
  - **S-065 Prescription PDF Export:** `weasyprint` added. `PrescriptionPDFGenerator` — Jinja2 HTML → PDF with clinic logo, doctor CRM, patient info, items, digital hash (sha256), watermark. Controlled substances render on separate page with blue border (Receituário Azul). Signature required before PDF generation. `GET /emr/prescriptions/{id}/pdf/` returns `application/pdf` with 1h Redis cache. `PRESCRIPTION_PDF_CACHE_TTL` env var. `backend/Dockerfile` + `docker-compose` add libcairo2, libpango, fonts-liberation for WeasyPrint OS deps. CI smoke test verifies WeasyPrint before pytest.
  - **S-066 Appointment Cancellation Waitlist:** `WaitlistEntry` model + migration (`emr/0012_waitlistentry.py`) with status machine (`waiting/notified/booked/expired/cancelled`) and preferred date/time ranges. Signal `on_appointment_cancelled` → `notify_next_waitlist_entry` Celery task sends WhatsApp. `expire_waitlist_notification` task fires after 30min countdown via `apply_async`. WhatsApp response handler routes `SIM`/`NÃO` from notified entries → book-or-skip. REST: `GET/POST /emr/waitlist/`, `DELETE /emr/waitlist/{id}/`. Frontend: `/appointments/waitlist` management view, "Entrar na fila de espera" on unavailable slots, status-badge sidebar panel.
  - **Sprint 15-17 catch-up (f135c28):** AI Scribe (Whisper service + `views_scribe.py` + `AudioRecorder` + `ScribeButton` + SOAP editor integration), DPA modal (`AIDPAStatus` migration `core/0009_aidpastatus.py` + `views_dpa.py` + `DPASignModal`), AI config page (`/configuracoes/ai`), patient check-in flow (`/waiting-room` + `WaitTimeCard`), WhatsApp appointment reminder uniqueness constraint (`whatsapp/0005_alter_appointmentreminder_unique...`).

### Fixed
- **DX-07:** `docs/PLAN_SPRINT15.md` migration table now documents django-tenants run order — use `migrate_schemas` (not `migrate`), shared-first then tenant-second.
- **DX-08:** `.github/workflows/ci.yml` backend-test installs libcairo2/libpango/fonts + smoke-tests WeasyPrint before pytest, catching OS-dep regressions that would otherwise surface as cryptic Cairo errors in S-065 PDF tests.
- `backend/conftest.py` (new): close stale DB connections at test-class boundaries to fix `TenantTestCase` teardown cascade.
- `backend/.dockerignore` (new): exclude `.venv` so docker build context reads cleanly on Windows (`.venv/lib64` is a symlink Docker can't traverse).

### Changed
- `backend/requirements/base.txt`: + `pyotp`, `qrcode[pil]` (MFA), `weasyprint` (PDF).
- `.env.example`: + `MFA_GRACE_PERIOD_DAYS`, `PRESCRIPTION_PDF_CACHE_TTL`.
- `.gitignore`: + pytest scratch files (`check_run*`, `fix_testdb`, `drop_testdb.py`, `uv.lock`).

## [0.9.0] — 2026-04-05

### Added
- **First Pilot Readiness (Sprint 14, S-054–S-061):** End-to-end pilot clinic operations — onboarding wizard, real PIX payments via Asaas, transactional email confirmations, demo seed data, 5 performance indexes, mobile-responsive pages, user guide, and pilot monitoring dashboard.
  - **S-054 Tenant Onboarding Wizard:** 5-step frontend wizard at `/setup` (clinic name, professional credentials, working hours click-to-toggle days, PIX key, completion screen). Backend: `POST /api/v1/emr/setup/professional/` (idempotent — creates/updates Professional + ScheduleConfig atomically), `GET /api/v1/emr/setup/status/`. `ProfessionalSetupSerializer` validates `council_type`, `council_state`, `working_days`, and slot duration.
  - **S-055 PIX Payment Integration (Asaas):** `AsaasService` (LGPD: name+email only, no CPF to Asaas), `PIXCharge` model, `AsaasChargeMap` (public schema webhook routing), `PIXChargeView` (idempotent), `AsaasWebhookView` (`hmac.compare_digest`, `select_for_update()` idempotency, tenant routing). Celery task `expire_pix_charges` every 5 min. `MIGRATION_MODULES` workaround for root-owned billing migrations dir.
  - **S-056 Transactional Email:** `EmailService.send_appointment_confirmation/reminder()`, HTML templates, signal receiver `on_appointment_paid` → `Celery.delay()`, daily 08:00 reminder beat task.
  - **S-057 Seed Data:** `make seed-demo tenant=<schema>` seeds patients, appointments, and 6 PIXCharge records with varied statuses.
  - **S-058 Performance Indexes:** RunSQL function index on `DATE(start_time AT TIME ZONE 'America/Sao_Paulo')`, GIN on `Patient.insurance_data`, composite `(action, created_at)` on AuditLog, `(status, expires_at)` on PIXCharge. `docs/PERFORMANCE.md`.
  - **S-059 Mobile Responsiveness:** Appointments page day-list card view on `<md` (patient name, time, status, action button); header/legend responsive. Setup wizard mobile-first.
  - **S-060 User Guide:** `docs/USER_GUIDE.md` — 10 sections in PT-BR including "AI em breve" section.
  - **S-061 Pilot Monitoring Dashboard:** `GET /api/v1/platform/pilot-health/` (platform admin) with per-tenant KPIs + system health. Frontend `/platform/monitor` — 30s auto-refresh, stale indicator, sparklines.
  - **DX:** `docs/DEVELOPMENT.md`, `docs/USER_GUIDE.md`, `.env.example` Asaas vars.

### Fixed
- `billing/models.py` missing `import uuid` for PIXCharge model.
- `apps/core/apps.py` imports `billing.services.tasks` in `ready()` to wire `appointment_paid` signal receiver.

## [0.8.0] — 2026-04-05

### Added
- **Pre-Production Hardening (Sprint 13, S-044–S-053):** Full production readiness — connection pooling, Redis cache, structured logging, Sentry tenant tagging, rate limiting, staging infra, CI/CD pipeline, and operations documentation.
  - **S-044/S-046 Production Settings Hardening:** `production.py` rewritten from 48 lines to full production config. DB connection pooling (`CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True`). Redis cache via `django_redis` replacing in-memory. Session engine switched to Redis (`SESSION_ENGINE=cache`). `SECURE_HSTS_PRELOAD=True`. Upload size limits (10 MB). `DATA_UPLOAD_MAX_MEMORY_SIZE`.
  - **S-046 Structured JSON Logging:** `python-json-logger==2.0.7` added. `LOGGING` config in `production.py` emits JSON with `tenant` and `request_id` fields on every log line. `TenantRequestLogFilter` injects schema name (falls back to `"shared"` in Celery context). `RequestIdMiddleware` generates UUID4 per request, echoed in `X-Request-ID` response header, cleaned up in `finally` block.
  - **S-045 Sentry Integration:** `sentry_sdk.init` with `DjangoIntegration` + `CeleryIntegration`, `traces_sample_rate=0.1`, `profiles_sample_rate=0.1`. `before_send` hook tags events with `connection.tenant.schema_name` for per-clinic Sentry triage. PHI stripping (`cpf`, `patient_id`, `patient_name`, `phone`, `email`) from `user` and `extra` dicts for LGPD compliance. `@sentry/nextjs@8` added to frontend. `sentry.client.config.ts` and `sentry.server.config.ts` with `maskAllText=true`, `blockAllMedia=true` Session Replay, PHI stripping in `beforeSend`. `next.config.mjs` wrapped with `withSentryConfig`.
  - **S-047 Global Rate Limiting:** `TenantUserRateThrottle` subclasses `UserRateThrottle` with `throttle:{schema}:{base_key}` cache key to prevent cross-tenant bucket collision in shared Redis. `DEFAULT_THROTTLE_CLASSES` + `DEFAULT_THROTTLE_RATES` added to `REST_FRAMEWORK` in `base.py` (anon: 100/hr, user: 1000/hr). `LoginRateThrottle` (5/min, `AnonRateThrottle` subclass) applied to `LoginView`.
  - **S-048 CI Fixes:** `ci.yml` branch trigger updated from `[main, develop]` to `[main, master, develop]` — CI was never running on production branch. `docker-validate` job condition updated to include `refs/heads/master`. `frontend/app/(dashboard)/farmacia/catalog/page.tsx`: added `anvisa_code?: string | null` to `Drug` type (pre-existing TS error).
  - **S-049 Staging Compose:** `docker-compose.staging.yml` using GHCR images (`vitali-backend` + `vitali-frontend`), `restart: always`, no exposed host DB/Redis ports, `--env-file .env.staging` pattern. `.env.staging.example` with all 20+ required env vars.
  - **S-050 Smoke Tests:** `scripts/smoke_test.sh` — 7 checks: `/health/` (200 + <500ms warning), `POST /api/v1/auth/login` (401 + `Content-Type: application/json`), `/api/schema/` (200), frontend (200), static files, Celery task execution (enqueue + `result.get(timeout=10)` with Redis ping fallback), HTTPS redirect. Exit 0 on pass, exit 1 with named failures.
  - **S-051 Staging CD Pipeline:** `.github/workflows/deploy-staging.yml` — triggers on push to master + `workflow_dispatch`. Build-and-push job (GHCR, sha + latest tags, layer caching). Deploy job via SSH: pre-deploy rollback snapshot using GHCR image names, pull + `up -d`, `migrate_schemas --shared`, `collectstatic`. Auto-rollback on smoke test failure.
  - **S-052 Operations Documentation:** `docs/DEPLOY.md` — 9-step quickstart, full env var reference table, GitHub Secrets table, rollback procedure (manual + automatic + specific tag), post-deploy verification. `docs/RUNBOOK.md` — reading JSON log lines by tenant/request_id, restarting services in correct order, Django shell with tenant context, Redis key inspection and flush procedures, Celery inspection. `docs/TENANT_MIGRATIONS.md` — additive-only migration rule, pre-migration per-tenant pg_dump snapshot, `migrate_schemas --shared` first then all tenants, single-tenant retry, rollback procedure with explicit downtime disclosure and `DROP SCHEMA / restore` steps.
  - **S-053 Hardening Tests:** `backend/apps/core/tests/test_middleware_hardening.py` — 17 tests covering `RequestIdMiddleware` (UUID4 header, uniqueness, thread-local cleanup, exception safety), `TenantRequestLogFilter` (tenant/request_id injection, shared fallback, always returns True), `TenantUserRateThrottle` (per-schema key scoping, cross-tenant isolation, anonymous None key), production settings (CONN_MAX_AGE, CONN_HEALTH_CHECKS, SESSION_ENGINE, CSRF_TRUSTED_ORIGINS as list).

### Fixed
- **Critical: `DATABASES` engine lost in production** — `production.py` rewrote `DATABASES` entirely, dropping `ENGINE=django_tenants.postgresql_backend` set in `base.py`. Fixed by using `.update()` instead of full reassignment. Would have broken all tenant schema routing on first production deploy.
- **Critical: CD rollback broken** — `deploy-staging.yml` tagged `vitali-django:rollback` / `vitali-nextjs:rollback` (nonexistent local names) instead of actual GHCR image paths. Rollback would silently fail. Fixed with `ghcr.io/{owner}/vitali-backend:rollback` naming.
- **Redis cache backend mismatch** — `CACHES` used `django.core.cache.backends.redis.RedisCache` (Django built-in) but specified `CLIENT_CLASS: django_redis.client.DefaultClient` (django-redis option). Changed backend to `django_redis.cache.RedisCache`.

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
