# Sprint 26: Production Readiness Gate

## Goal

Remove release blockers that can pass feature QA but fail at deploy time.

## Shipped Scope

### S26-01: Next.js Observability Bootstrap

- Moved frontend Sentry initialization into `frontend/instrumentation.ts`.
- Removed the deprecated `sentry.server.config.ts` path that generated build warnings.
- Added `frontend/app/global-error.tsx` so App Router render crashes are reported.
- Preserved LGPD-safe event filtering for known PHI fields in user and extra contexts.

### S26-02: Staging Image Contract

- Aligned `GHCR_REPO` with the package names published by CI.
- Staging now pulls `ghcr.io/<owner>/vitali-backend` and `ghcr.io/<owner>/vitali-frontend`.
- Deploy docs and `.env.staging.example` use the same owner-only value.

### S26-03: Deploy Smoke Gate

- `scripts/smoke_test.sh` now targets the public frontend URL instead of assuming port 3000 is exposed.
- The script accepts `COMPOSE_FILE` and `COMPOSE_ENV_FILE`, so staging and local checks use the same gate.
- Celery is verified through a real broker round-trip using `apps.core.tasks.smoke_ping`.

### S26-04: CI Release Gates

- Backend mypy is blocking again.
- Docker validation runs on pull requests, not only after merge to `master`.
- CI validates local and staging compose config plus smoke script syntax before image builds.

### S26-05: Multi-Tenant Celery Readiness

- Periodic billing, waitlist, and WhatsApp tasks now iterate tenant schemas instead of querying tenant tables from `public`.
- The Celery worker imports waitlist tasks explicitly, so beat schedules cannot enqueue unregistered task names.
- A small `apps.core.tasks.smoke_ping` task provides a real broker/worker round-trip for deploy smoke tests.

### S26-06: Deterministic Docker Dev Runtime

- The Next.js dev container now installs from `npm ci` instead of mutating dependencies with `npm install`.
- The host lockfile is preserved while Linux-only optional dependency metadata is installed inside the container volume.
- The E2E clinical journey waits atomically for the encounter navigation and allows enough time for first Next.js dev compilation.

### S26-07: Runtime-Safe Local Reverse Proxy

- Nginx now resolves `django` and `nextjs` through Docker DNS at request time.
- Recreating Django or Next.js no longer leaves nginx proxying to stale container IPs.
- The local smoke gate covers this failure mode through backend, static, frontend, and Celery checks via `http://localhost`.

### S26-08: Frontend Security Baseline

- Upgraded Next.js to `15.5.15`, `eslint-config-next` to `15.5.15`, and `@sentry/nextjs` to `10.51.0`.
- Migrated App Router cookies, route params, and Sentry client/request hooks to the Next 15/Sentry 10 contracts.
- Replaced deprecated `next lint` with the ESLint CLI and kept `npm audit --audit-level=high` passing.

### S26-09: Migration Drift Gate

- Added the missing AI migration for `AIScribeSession` index names.
- Verified `makemigrations --check --dry-run` reports no model drift.

## Acceptance Criteria

- `npm run build` no longer emits Sentry setup warnings for deprecated server config, missing global error capture, or public source maps.
- `docker compose -f docker-compose.staging.yml --env-file .env.staging.example config` resolves image names to the same GHCR packages published by CI.
- `scripts/smoke_test.sh` can validate backend health, auth, schema, frontend, static files, and Celery without hard-coded container names.
- GitHub Actions blocks PRs on backend type errors and Docker build regressions.
- Celery beat tasks run safely outside an active tenant request context.
- Local Docker dev can recreate the frontend container without rewriting `frontend/package-lock.json`.
- The product-critical clinical journey E2E passes against the Docker stack.
- Nginx continues serving backend and frontend routes after app containers are recreated.
- Frontend dependency audit has no high-severity advisories.
- Django model state has no missing migrations.

## Verification Commands

```bash
bash -n scripts/smoke_test.sh
GHCR_REPO=tropeks IMAGE_TAG=ci docker compose -f docker-compose.staging.yml --env-file .env.staging.example config
docker compose config
docker compose exec -T django python manage.py makemigrations --check --dry-run
docker compose exec -T django pytest -v apps/core/tests/test_tasks.py
docker compose exec -T django pytest -v apps/core/tests/test_tenancy.py apps/billing/tests/test_pix.py::PIXChargeExpiryTaskTest apps/emr/tests/test_waitlist.py apps/whatsapp/tests/test_tasks.py
docker compose exec -T nginx nginx -t
bash scripts/smoke_test.sh
cd frontend && npm audit --audit-level=high
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm run build
cd frontend && npx playwright test --project=chromium
```
