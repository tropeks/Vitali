<!-- /autoplan restore point: /home/rcosta00/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260405-142833.md -->

# Sprint 13 — Pre-Production Hardening

**Version target:** v0.8.0
**Branch:** master
**Base commit:** e3ac477

---

## Scope

1. **docs/DEPLOY.md + docs/RUNBOOK.md** — full staging→prod deploy procedure
2. **Harden production.py** — DATABASE pooling, structured LOGGING, CACHES, SESSION_ENGINE, CSRF_TRUSTED_ORIGINS, CONN_MAX_AGE
3. **Sentry integration** — backend + frontend, tenant tagging, performance tracing
4. **Structured JSON logging** — python-json-logger, request IDs, tenant IDs in every log line
5. **docs/TENANT_MIGRATIONS.md** — safe migrate_schemas on N tenants in prod + rollback
6. **docker-compose.staging.yml** — staging compose separate from dev
7. **Global rate limiting** — django-ratelimit (or DRF throttling) on all public endpoints
8. **Fix test suite** — farmacia/catalog/page.tsx:290 `anvisa_code` TS error + backend failures; fix CI workflow triggering on wrong branch (`main`/`develop` vs `master`)
9. **scripts/smoke_test.sh** — post-deploy health check script
10. **.github/workflows/deploy-staging.yml** — staging CD pipeline

---

## Context: What Already Exists

| Item | Status |
|------|--------|
| `production.py` | 48 lines — basic SECURE_* headers, Sentry skeleton, email. Missing: pooling, CACHES, SESSION_ENGINE, CSRF_TRUSTED_ORIGINS, JSON logging |
| `sentry-sdk==2.21` | In requirements/production.txt — but no tenant scope_context, no before_send hook |
| `LOGGING` in base.py | Plain-text verbose format — no JSON, no request IDs, no tenant IDs |
| `apps/ai/rate_limiter.py` | Per-tenant Redis rate limiter for AI only — no global API rate limiting |
| DRF `DEFAULT_THROTTLE_CLASSES` | Not configured |
| `ci.yml` | Runs on `branches: [main, develop]` — **never triggers on master pushes** (bug) |
| `scripts/` | Does not exist |
| `docker-compose.staging.yml` | Does not exist |
| `.github/workflows/deploy-staging.yml` | Does not exist |
| TS error `anvisa_code` | `frontend/app/(dashboard)/farmacia/catalog/page.tsx:290` — `Drug` type missing `anvisa_code` field |

---

## Story Breakdown

### S-044 — Production Settings Hardening
**Files:** `backend/vitali/settings/production.py`, `backend/requirements/production.txt`

Add to production.py:
- `DATABASES` with `CONN_MAX_AGE=60`, `OPTIONS={'pool': True}` (psycopg3) or connection string pooling hint
- `CACHES` pointing to Redis with key prefix `vitali:{tenant}:`
- `SESSION_ENGINE = "django.contrib.sessions.backends.cache"` + `SESSION_CACHE_ALIAS = "default"`
- `CSRF_TRUSTED_ORIGINS` from env var `CSRF_TRUSTED_ORIGINS`
- Structured JSON logging override (replaces base.py plain-text for prod)
- `SECURE_HSTS_PRELOAD = True`
- `DATA_UPLOAD_MAX_MEMORY_SIZE` / `FILE_UPLOAD_MAX_MEMORY_SIZE` limits
- `CONN_HEALTH_CHECKS = True`

### S-045 — Sentry Tenant Tagging
**Files:** `backend/vitali/settings/production.py`, `frontend/next.config.mjs` (or `sentry.client.config.ts`)

Backend: Add `before_send` hook that sets `scope.set_tag("tenant", connection.tenant.schema_name)` via `django_tenants.utils.get_tenant`. Add `profiles_sample_rate=0.1`. Add `environment` tag from `env("ENVIRONMENT", default="production")`.

Frontend: Install `@sentry/nextjs`, add `sentry.client.config.ts` + `sentry.server.config.ts` with DSN from env. Add `withSentryConfig` to `next.config.mjs`.

### S-046 — Structured JSON Logging + Request IDs
**Files:** `backend/requirements/production.txt`, `backend/vitali/settings/production.py`, `backend/apps/core/middleware.py`

- Add `python-json-logger==2.0.7` to production requirements
- In production.py LOGGING: replace `verbose` formatter with `pythonjsonlogger.jsonlogger.JsonFormatter`
- Add fields: `asctime`, `name`, `levelname`, `message`, `tenant`, `request_id`
- Add `RequestIdMiddleware` to `apps/core/middleware.py`:
  - Generates UUID4 request ID on each request
  - Stores in `threading.local()` + response header `X-Request-ID`
  - **Must use `finally` block to clear thread-local on exit (mirror CurrentUserMiddleware pattern)**
  - Injects into log context via logging filter
- Add `TenantLogFilter` that injects `connection.tenant.schema_name` into every log record
  - **Must guard: `tenant = getattr(connection, 'tenant', None)` → default `"shared"` when None (Celery tasks)**

### S-047 — Global Rate Limiting
**Files:** `backend/vitali/settings/base.py`, `backend/requirements/base.txt`, `backend/apps/core/throttles.py`

Two-layer approach:
1. **`TenantUserRateThrottle`** subclass in `apps/core/throttles.py` — override `get_cache_key()` to return `throttle:{schema_name}:user:{user_id}` to prevent cross-tenant cache key collision (critical in multi-tenant: user #1 in tenant_a and user #1 in tenant_b must have separate buckets).
2. **DRF `DEFAULT_THROTTLE_CLASSES`** in base.py — `AnonRateThrottle` (100/hour) + `TenantUserRateThrottle` (1000/hour). No new package needed.
3. **Per-endpoint overrides** via `throttle_classes` on sensitive views: login (5/min), webhook (already rate-limited), AI (existing per-tenant limiter).

No `django-ratelimit` dependency needed — DRF has built-in throttling. The existing AI per-tenant limiter stays.

### S-048 — Fix Test Suite + CI Branch Trigger
**Files:** `.github/workflows/ci.yml`, `frontend/app/(dashboard)/farmacia/catalog/page.tsx`

- Fix CI: add `master` to `branches` lists in `push` and `pull_request` triggers (lines 5-6)
- **Also fix `ci.yml:141`**: `if: github.ref == 'refs/heads/main'` → `refs/heads/master` (docker-validate job)
- Fix TS: add `anvisa_code?: string | null` to the `Drug` interface in catalog/page.tsx:~line 15
- Run backend tests locally via docker to identify any other failures (expect clean — Sprint 12 fixes were validated via `ast.parse`)

### S-049 — docker-compose.staging.yml
**Files:** `docker-compose.staging.yml`, `.env.staging.example`

Staging compose differences from dev:
- `DJANGO_SETTINGS_MODULE: vitali.settings.production`
- `DEBUG: "False"`
- No host port exposure for postgres/redis (internal only)
- `restart: always` instead of `unless-stopped`
- Nginx service with Let's Encrypt placeholder
- `replicas: 2` on django for basic HA test

### S-050 — Smoke Test Script
**Files:** `scripts/smoke_test.sh`

Checks:
1. `GET /health/` → 200, response time < 500ms
2. `POST /api/v1/auth/login` with bad creds → 401, Content-Type: application/json (not a 500 or HTML error page)
3. `GET /api/v1/schema/` → 200 (OpenAPI schema validates Django is up)
4. Frontend `GET /` → 200 (Next.js serving)
5. **Celery task execution**: enqueue no-op task via management command or health endpoint → assert completes within 10s (not just Redis ping)
6. Static file serving: `GET /static/admin/css/base.css` → 200 (Nginx config valid)
7. HTTPS redirect (if real domain): `curl --no-location http://domain` → 301

Exit 0 on all pass, exit 1 with specific check name and response in failure message.

### S-051 — deploy-staging.yml
**Files:** `.github/workflows/deploy-staging.yml`

Trigger: push to `master` (manual `workflow_dispatch` also).
Steps: checkout → build backend image → build frontend image → push to GHCR → SSH to staging → **tag current running images as rollback tags** → `docker compose -f docker-compose.staging.yml pull && up -d` → run `scripts/smoke_test.sh` → on failure: auto-rollback via rollback tag → notify on failure.

**Required GitHub Secrets (must be enumerated in DEPLOY.md):**
`GHCR_TOKEN`, `STAGING_SSH_KEY`, `STAGING_HOST`, `STAGING_USER`, `DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `SENTRY_DSN`, `CSRF_TRUSTED_ORIGINS`, `NEXT_PUBLIC_API_URL`, `FIELD_ENCRYPTION_KEY`, `WHATSAPP_EVOLUTION_URL`, `WHATSAPP_WEBHOOK_SECRET`

### S-052 — Documentation
**Files:** `docs/DEPLOY.md`, `docs/RUNBOOK.md`, `docs/TENANT_MIGRATIONS.md`

**DEPLOY.md required sections:**
1. Prerequisites (Docker, GHCR access, SSH key)
2. GitHub Secrets reference table (all 13 secrets: name, type, example, source)
3. Numbered quickstart: clone → fill .env.staging → configure secrets → push → verify
4. Rollback procedure: exact docker commands + image tag convention
5. Post-deploy verification beyond smoke_test.sh (Sentry release, log check)

**RUNBOOK.md required sections:**
1. How to identify affected tenant from a JSON log line (field: `tenant`)
2. Restart a single service without downtime: `docker compose restart {service}`
3. Django shell on staging: `docker exec -it vitali-django-1 python manage.py shell`
4. Redis flush procedure (accidental cache poisoning)
5. Per-tenant migration: `python manage.py migrate_schemas --schema={slug}`
6. Celery task inspection: `celery -A vitali inspect active`

**TENANT_MIGRATIONS.md required sections:**
1. **Rule: all tenant migrations must be additive-only** (no column drops/renames without two-phase deploy)
2. Pre-migration snapshot: `pg_dump -n {schema} > /backups/pre_{schema}_$(date +%s).sql` (per-tenant, before migrate_schemas)
3. Running migrations: `migrate_schemas --shared` first, then `migrate_schemas` for all tenants
4. Retrying a single failed tenant: `migrate_schemas --schema={slug}`
5. Rollback for already-migrated tenants: stop app → restore pg_dump per schema → redeploy previous image (requires downtime — document blast radius explicitly)
6. Backward-compat test: run Django check in CI that verifies the new migration works against the old schema version

### S-053 — Middleware Hardening Tests
**Files:** `backend/apps/core/tests/test_middleware_hardening.py`

New test file covering all new/modified middleware:
- `RequestIdMiddleware`: header set, finally cleanup on exception, thread-local isolation
- `TenantLogFilter`: active tenant, None tenant (Celery) → "shared", public schema
- `TenantUserRateThrottle`: schema-prefixed key, cross-tenant isolation, 429 + Retry-After
- Settings validation: `CSRF_TRUSTED_ORIGINS` is a list, Sentry before_send strips PHI

---

## NOT In Scope (Sprint 13)

- Kubernetes / ECS migration (infrastructure only) — defer to Sprint 14
- Let's Encrypt auto-renewal automation (manual setup for now)
- Multi-region failover
- PagerDuty / alerting integration (Sentry alerts sufficient for now)
- WAF / DDoS protection (Cloudflare layer — infrastructure decision)
- Automated DB backup testing / restore drills

---

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|---------|
| 1 | CEO | Rate limiting via DRF built-in throttle (not django-ratelimit) | Mechanical | P4+P5 | DRF covers the use case; no new dependency | django-ratelimit |
| 2 | CEO | Add `master` to CI branch triggers (fix silent bug) | Mechanical | P6 | CI never ran on master — bug. 2-line fix. | Leave broken |
| 3 | CEO | Include @sentry/nextjs in S-045 | Mechanical | P1+P2 | In blast radius, <4h CC effort | Defer to Sprint 14 |
| 4 | Eng | 15 files OK — all config/infra, 0 new service classes | Mechanical | P1 | Hardening sprint; no new services introduced | Scope reduction |
| 5 | Eng | TenantLogFilter must guard `connection.tenant` against None (Celery) | Mechanical | P5 | AttributeError on every Celery task log otherwise | Ignore Celery path |
| 6 | Eng | CSRF_TRUSTED_ORIGINS must use `env.list()` not `env()` | Mechanical | P5 | Django iterates it — plain string silently breaks CSRF | env() string |
| 7 | Eng | Sentry `before_send` strips PHI fields (cpf, patient_id, user) | Mechanical | P1 | LGPD: Brazilian health data cannot reach Sentry servers | Skip stripping |
| 8 | Eng | `TenantUserRateThrottle` subclass with `{schema}:{user_id}` cache key | Mechanical | P5 | DRF default key collides across tenants sharing numeric user IDs | DRF default UserRateThrottle |
| 9 | Eng | Fix `ci.yml:141` docker-validate ref to `refs/heads/master` in S-048 | Mechanical | P6 | Docker builds never validated on master push | Leave broken |
| 10 | Eng | Add `test_middleware_hardening.py` for RequestId, TenantFilter, Throttle | Mechanical | P1 | 14 coverage gaps; infra bugs are silent otherwise | Skip tests |
| 11 | DX | DEPLOY.md must include env var inventory + numbered quickstart | Mechanical | P1 | Without it contractor TTHW is 3-4 hours not 30 minutes | Minimal doc |
| 12 | DX | TENANT_MIGRATIONS.md must codify additive-only migration rule | Mechanical | P5 | Split schema state after mid-run failure is undefined behavior | Describe failure only |
| 13 | DX | deploy-staging.yml must tag current images before deploy for rollback | Mechanical | Reversibility | Partial deploy leaves inconsistent container state | Manual rollback only |
| 14 | DX | smoke_test.sh must add Celery task execution check | Mechanical | P1 | Stalled Celery worker passes Redis ping but tasks are dead | Skip |
| 15 | DX | All 10+ GitHub Secrets enumerated in DEPLOY.md | Mechanical | P5 | First-deploy stalls if secrets are discovered on failure | Discover on failure |

---

## Test Plan

- `pytest backend/apps/` — full backend test suite (no new test files needed for infra)
- `frontend/node_modules/.bin/tsc --noEmit` — must pass clean
- `scripts/smoke_test.sh` after staging deploy
- CI workflow triggers on `master` push


---

## GSTACK REVIEW REPORT

| Review | Phase | Runs | Status | Key Findings |
|--------|-------|------|--------|-------------|
| CEO Review | Phase 1 | 1 | issues_open | 1 USER CHALLENGE (scope vs pilot focus); rate limiting threat model clarified |
| Eng Review | Phase 3 | 1 | issues_open | 6 issues: 2 P1 (Celery TenantFilter, ci.yml:141), 2 P2 (CSRF list, Sentry PHI, throttle collision), 1 P3 (middleware cleanup test) — all auto-decided |
| DX Review | Phase 3.5 | 1 | issues_open | 5 issues: 1 critical (tenant migration rollback), 3 high (quickstart, rollback, secrets), 1 medium (smoke test gaps) — all auto-decided |
| Design Review | — | 0 | skipped | No UI scope |
| Dual Voices | All | 1 | subagent-only | Codex unavailable — Claude subagent only |

**VERDICT:** PLAN ENHANCED — 15 auto-decisions applied across CEO/Eng/DX phases. 1 USER CHALLENGE remains for approval gate. Plan updated with all findings. Ready for implementation after approval.

