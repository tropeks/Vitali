# Vitali — Development Setup

## Prerequisites

- Docker Desktop (or Docker + Docker Compose v2)
- Node.js 20+ (for frontend)
- Python 3.12+ (for local backend without Docker)

## Quick start

```bash
# 1. Copy environment file
cp .env.example .env
# Edit .env with your values

# 2. Start all services
make up

# 3. Run migrations
make migrate
make migrate-tenant

# 4. Create your first tenant
make create-tenant

# 5. Seed demo data
make seed-demo tenant=<schema_name>

# 6. Access
# Backend API: http://localhost:8000/api/v1/
# Frontend:    http://localhost:3000
# Django admin: http://localhost:8000/admin/
```

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

```bash
make test
# Or with coverage:
make test-cov
# Or specific file:
make test args="apps/billing/tests/"
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
