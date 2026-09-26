# Vitali — Development Setup

## Prerequisites

- Docker Desktop (or Docker + Docker Compose v2)
- Node.js 20+ (for frontend)
- Python 3.12+ (for local backend without Docker)

## Quick start

> **This is for your own machine.** `docker-compose.yml` publishes Postgres
> (`5435`), Redis (`6379`, no password) and Django (`8000`) on **every
> interface**. On a personal laptop behind your own firewall that is fine. On a
> shared machine it is not — see [The forge rule](#the-forge-rule) below.

```bash
# 1. Copy environment file
cp .env.example .env
# Edit .env with your values

# 2. Start all services
make up

# 3. Run migrations
make migrate
make migrate-tenant

# 4. Bootstrap the public tenant + your first clinic (idempotent — safe to re-run)
BOOTSTRAP_ADMIN_PASSWORD='<choose-one>' docker compose exec \
  -e BOOTSTRAP_ADMIN_PASSWORD django python manage.py bootstrap_beta \
  --public-domain localhost \
  --clinic-slug demo --clinic-domain demo.localhost \
  --admin-email admin@demo.localhost

# 5. Pre-create this month's and next month's audit-log partitions (idempotent)
docker compose exec django python manage.py ensure_audit_partitions

# 6. Seed demo data
make seed-demo tenant=demo

# 7. Access
# Backend API: http://localhost:8000/api/v1/
# Frontend:    http://localhost:3000
# Django admin: http://localhost:8000/admin/
```

### Creating a tenant: `bootstrap_beta` for a fresh environment, `provision_tenant` for one clinic

`bootstrap_beta` (`backend/apps/core/management/commands/bootstrap_beta.py`)
creates, idempotently: the public tenant and its domain, the clinic tenant and
its domain(s), the default roles in the clinic schema, the clinic admin (from
`BOOTSTRAP_ADMIN_PASSWORD`, never a CLI argument) with its
`UserTenantMembership`, a beta plan + subscription, and `FeatureFlag` rows that
match the subscription's modules. Run `python manage.py bootstrap_beta --help`
for the options (`--module` narrows the module set). Use this to stand up a
whole fresh environment (public tenant + one demo clinic), not to add ONE
clinic to an environment that already exists.

To provision a single clinic — self-serve signup, the platform-admin API
(`POST /api/v1/platform/tenants`), and `manage.py provision_tenant` (also
what `make create-tenant` calls) — all three now go through the exact same
function, `apps.core.services.provisioning.provision_tenant` (ordem 022): it
creates the tenant + schema, routing domain, default roles, owner user +
membership, trial subscription + feature flags, and the owner's two
dedicated audit-log partitions — transactionally, dropping the schema on
partial failure. Run `python manage.py provision_tenant --help` for the
options. There is no `--password` argument by design: the owner activates via
the same set-password e-mail link self-serve signup issues.

**Removed:** `scripts/provision_tenant.sh` (ordem 022) — it interpolated the
clinic name into a `manage.py shell -c` string, so a name with an apostrophe
broke it and a name crafted for it could run arbitrary code with every
clinic's database credentials. `make create-tenant` no longer runs an
interactive `shell -c` blob either; it calls `manage.py provision_tenant`
with `slug=`/`name=`/`domain=`/`owner_email=`/`owner_name=` make variables.

## Local PIX Setup {#local-pix-setup}

PIX payments use the [Asaas](https://asaas.com) payment gateway (Brazilian PIX-first API).

### 1. Create a sandbox account

Go to [sandbox.asaas.com](https://sandbox.asaas.com) and create a free account.

### 2. Get your API key

In the Asaas dashboard: **Configurações → Integrações → Chave de API**.

Sandbox keys start with `$aact_`. Copy it.

### 3. Configure .env

```bash
ASAAS_API_KEY=$aact_your_key_here
ASAAS_WEBHOOK_TOKEN=any-random-secret-32-chars
ASAAS_ENVIRONMENT=sandbox
PIX_CHARGE_EXPIRY_MINUTES=30
```

### 4. Configure webhook (optional for local dev)

For webhook testing locally, use [ngrok](https://ngrok.com) to expose your local server:

```bash
ngrok http 8000
# Note the https URL, e.g. https://abc123.ngrok.io

# In Asaas dashboard: Configurações → Notificações → Webhook
# URL: https://abc123.ngrok.io/api/v1/billing/pix/webhook/
# Events: PAYMENT_RECEIVED, PAYMENT_CONFIRMED
```

Set `ASAAS_WEBHOOK_TOKEN` to the token you configured in Asaas.

### 5. Test the flow

```bash
# Create a PIX charge via the appointments page UI
# Or via API:
curl -X POST http://localhost:8000/api/v1/billing/pix/charges/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"appointment_id": "<uuid>", "amount": "150.00"}'
```

In sandbox, you can simulate payment completion via the Asaas dashboard.

---

## Running tests

### Where tests run

1. **CI — the default path.** `.github/workflows/ci.yml` runs on every push to
   `main`, `master`, `develop` and `order/**`, and on pull requests against
   `main`, `master`, `develop` and `onda0-perimetro-multitenant` — so an order
   branch is tested **before** it is merged (order 005). Commits that touch only
   `.maestro/**`, `docs/**` or `**/*.md` are skipped by `paths-ignore`; to ask
   for a run anyway, use `gh workflow run ci.yml --ref <branch>`. Five jobs:

   | Job | What it runs |
   |---|---|
   | `Backend — Lint & Types` | `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, compiled translation catalogs |
   | `Backend — Tests` | `migrate_schemas --shared`, then `pytest --cov=apps` over the whole suite |
   | `Frontend — Lint, Types & Unit` | `npm run lint`, `npm run type-check`, `npm test` (vitest — order 012) |
   | `Frontend — E2E (Playwright)` | Playwright against the compose stack |
   | `Docker — Validate Build` | `bash -n` on the ops scripts, `docker compose config` on every compose file, image builds |

2. **The lab — when you need a run before pushing.** Tests run in a throwaway
   container on the lab host through the `lab` Docker context. Nothing is
   published on a host port.
3. **Your own machine** — `make test` below, with the local compose stack.

### The forge rule

> **Never bring up the Vitali compose stack on the forge — not even "for a
> minute".** The forge is a shared machine that holds secrets. On 17/09 a
> `docker compose up` from `master` there published Redis without a password,
> Postgres and Django on `0.0.0.0` to the LAN for 1h46. Tests go to CI or to the
> lab. The rule is about the forge; it does not forbid `make up` on your own
> machine.

### Running the backend suite on the lab

Prerequisites on the lab: a Docker network with a Postgres and a Redis attached
and **no published ports** (today: containers `v018-pg` and `v018-redis` on
network `v018net`).

Use the wrapper (order 027). It is the recipe below, executable:

```bash
scripts/pytest.sh <target>          # e.g. apps/core/tests/test_auth.py -x
scripts/pytest.sh                   # the whole suite
PYTEST_NO_BUILD=1 scripts/pytest.sh <target>              # reuse the images
PYTEST_CMD="ruff check apps/ vitali/" scripts/pytest.sh   # another command in the image
```

What it runs:

```bash
# 1. Test image with dev dependencies (pytest, ruff, mypy)
docker --context lab build --build-arg INSTALL_DEV=true -t vitali-test:x ./backend

# 2. Overlay: scripts/ at /scripts and the dev compose files at / (REQUIRED).
#    Build context = a temp dir with scripts/, docker-compose.yml and
#    docker-compose.override.yml, and this Dockerfile:
#      FROM vitali-test:x
#      COPY scripts /scripts
#      COPY docker-compose.yml docker-compose.override.yml /

# 3. Run, with a unique --name
docker --context lab run --rm --name vpytest-<ts>-<pid> --network v018net \
  -e DJANGO_SETTINGS_MODULE=vitali.settings.development \
  -e DATABASE_URL=postgres://vitali:vitali@postgres:5432/vitali \
  -e REDIS_URL=redis://redis:6379/0 \
  -e COVERAGE_FILE=/tmp/.coverage \
  vitali-test:x-full pytest <target> -q --no-header -p no:cacheprovider
```

Why each piece is there:

- **`--context lab`, always** — the wrapper drops `DOCKER_HOST`/`DOCKER_CONTEXT`
  and never talks to the local daemon.
- **`sg docker`** — needed when your login session predates your addition to
  the `docker` group; the wrapper re-executes itself under it.
- **`COVERAGE_FILE=/tmp/.coverage`** — without it pytest-cov stops with an
  `INTERNALERROR` writing its data file (uid mismatch: 1001 vs 1000). `/tmp` is
  always writable.
- **The `scripts/` overlay** — `apps/core/tests/test_drill_metric.py` executes
  `/scripts/drill_metric.sh`. Without the overlay those 5 tests fail, and the
  failure is **not** environmental noise to wave away.
- **The compose files in the overlay** — `apps/core/tests/test_compose_exposure.py`
  (order 027) reads `docker-compose.yml` and `docker-compose.override.yml` and
  fails when they are missing: a guard that skips itself is a false green.

Reference measurement: the whole backend suite on 26/09, on `fca984f` — 3,899
passed, 45 skipped, 0 failed, in about 1h47.

### Local backend tests (your own machine)

```bash
make test
# Or with coverage:
make test-cov
# Or specific file:
make test args="apps/billing/tests/"
```

### Frontend unit tests (vitest)

Run on the host with `frontend/node_modules` installed — no compose needed:

```bash
cd frontend
npm test            # vitest run — the same command CI gates on
npm run test:watch  # watch mode
npm run lint && npm run type-check
```

## Code style

```bash
make lint    # ruff check
make fmt     # ruff format
```

## Celery workers (local, without Docker)

```bash
# Worker
make run-worker

# Beat scheduler (periodic tasks)
make run-beat
```

## Dependency lockfile

Production dependencies are installed from a **pinned, hashed lockfile** so image
builds are reproducible and tamper-resistant.

- **Sources (human-edited, pip-tools `.in`-style):** `backend/requirements/base.txt`
  and `backend/requirements/production.txt`. These hold the direct deps and may use
  ranges (`>=`, `<`). Edit these to add/remove/bump a dependency.
- **Lock (generated, do not hand-edit):** `backend/requirements/production.lock`.
  It pins every direct **and transitive** dependency to an exact `==` version with
  `--hash=sha256:...` lines. The `Dockerfile` installs production deps with
  `pip install --require-hashes -r requirements/production.lock`.

### Regenerating the lock

After editing `base.txt` or `production.txt`, regenerate the lock **inside the same
base image as the Dockerfile** (`python:3.12-slim`) so wheels, environment markers,
and hashes match exactly what CI builds:

```bash
cd backend
docker run --rm -v "$PWD":/w -w /w python:3.12-slim sh -c \
  "pip install --no-cache-dir pip-tools && \
   pip-compile --quiet --generate-hashes \
     --output-file requirements/production.lock requirements/production.txt"
```

(`production.txt` already includes `-r base.txt`, so the lock covers the full
production closure.) Commit both the changed source file(s) and the regenerated
`production.lock`. The CI **Docker — Validate Build** job builds the image from the
lock with `--require-hashes` and fails loudly if the lock is stale or a hash is wrong.

`pip-tools` is available locally via `requirements/development.txt`, but the
`docker run` route above is preferred for an exact image match.

> Dependabot continues to bump the **source pins** in `base.txt`/`production.txt`;
> regenerate the lock as part of reviewing each bump.

## Environment variables reference

See `.env.example` for all available variables with descriptions.

Key variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | — | Django secret key |
| `DATABASE_URL` | Yes | postgres://vitali:vitali@localhost:5435/vitali | PostgreSQL connection |
| `REDIS_URL` | Yes | redis://localhost:6379/0 | Redis for Celery + cache |
| `ASAAS_API_KEY` | PIX only | — | Asaas payment gateway key |
| `ASAAS_WEBHOOK_TOKEN` | PIX only | — | Webhook validation token |
| `ASAAS_ENVIRONMENT` | No | sandbox | `sandbox` or `production` |
| `ANTHROPIC_API_KEY` | AI features | — | Claude API key |
| `WHATSAPP_EVOLUTION_API_KEY` | WhatsApp | — | Evolution API key |
