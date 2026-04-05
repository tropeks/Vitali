# Vitali — Operations Runbook

> Day-to-day operational procedures for staging and production. For initial deployment, see docs/DEPLOY.md.

---

## 1. Reading JSON Log Lines

All Django logs are structured JSON. Each line has at minimum:

```json
{"asctime": "2024-01-15 14:23:01,123", "levelname": "ERROR", "name": "django.request", "message": "...", "tenant": "clinica_alfa", "request_id": "3f2a1b4c-..."}
```

Key fields:

| Field | Meaning |
|-------|---------|
| `tenant` | Schema name of the affected clinic (or `"shared"` for platform-level) |
| `request_id` | UUID4 — correlate all log lines from the same HTTP request |
| `levelname` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `name` | Logger name (e.g. `django.request`, `apps.billing`) |

### Find all errors for a specific tenant

```bash
docker compose -f docker-compose.staging.yml logs django \
  | grep '"tenant": "clinica_alfa"' \
  | grep '"levelname": "ERROR"'
```

### Trace a full request by ID

```bash
docker compose -f docker-compose.staging.yml logs django \
  | grep '"request_id": "3f2a1b4c-abc1-..."'
```

### Stream live errors only

```bash
docker compose -f docker-compose.staging.yml logs -f django \
  | grep '"levelname": "ERROR"'
```

---

## 2. Restarting Services Without Downtime

`docker compose restart` sends SIGTERM then waits for the container to exit gracefully (30s timeout by default) before bringing it back up. It does NOT rebuild the image.

### Restart a single service

```bash
cd /opt/vitali
docker compose -f docker-compose.staging.yml restart django
docker compose -f docker-compose.staging.yml restart celery-worker
docker compose -f docker-compose.staging.yml restart celery-beat
docker compose -f docker-compose.staging.yml restart nextjs
docker compose -f docker-compose.staging.yml restart nginx
```

### Verify the service came back healthy

```bash
docker compose -f docker-compose.staging.yml ps
# Wait for "healthy" status on django before restarting celery-worker
```

### Restart order for zero-downtime

When restarting multiple services, follow this order to minimize errors:

1. `celery-beat` (no traffic impact)
2. `celery-worker` (no traffic impact)
3. `django` (Nginx queues requests for up to 30s)
4. `nextjs` (only impacts SSR pages)
5. `nginx` last, and only if config changed

---

## 3. Django Shell on Staging

```bash
# Interactive shell
docker compose -f docker-compose.staging.yml exec django python manage.py shell

# One-liner (non-interactive, useful in scripts)
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.count())"
```

### Tenant-aware shell (switch to a specific tenant schema)

```python
from django_tenants.utils import schema_context

with schema_context("clinica_alfa"):
    from apps.patients.models import Patient
    print(Patient.objects.count())
```

### List all tenants

```python
from apps.tenants.models import Tenant
for t in Tenant.objects.all():
    print(t.schema_name, t.name)
```

---

## 4. Redis Operations

### Check Redis connectivity

```bash
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" ping
# Expected: PONG
```

### Flush a specific key prefix (e.g. cache poisoning on one tenant)

```bash
# List affected keys first (never flush blindly)
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" --scan --pattern "vitali:clinica_alfa:*"

# Delete matching keys
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" --scan --pattern "vitali:clinica_alfa:*" \
  | xargs -r docker compose -f docker-compose.staging.yml exec -T redis \
    redis-cli -a "$REDIS_PASSWORD" DEL
```

### Flush throttle cache for a user (e.g. locked out of login)

```bash
# DRF throttle key format: throttle:{schema}:throttle_user_{user_id}
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" DEL "throttle:clinica_alfa:throttle_user_42"

# Login throttle (anon, by IP)
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" --scan --pattern "throttle:*:throttle_anon_*" \
  | xargs -r docker compose -f docker-compose.staging.yml exec -T redis \
    redis-cli -a "$REDIS_PASSWORD" DEL
```

### Flush ALL cache (last resort — causes a cold-start performance hit)

```bash
# WARNING: This will clear all sessions, throttle counts, and cached data.
# All active users will be logged out.
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" FLUSHDB
```

---

## 5. Running Migrations

See `docs/TENANT_MIGRATIONS.md` for the safe procedure with rollback steps.

Quick reference:

```bash
# Run all shared (public schema) migrations
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py migrate_schemas --shared --noinput

# Run migrations for a single tenant
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py migrate_schemas --schema=clinica_alfa --noinput

# Check for unapplied migrations
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py showmigrations | grep "\[ \]"
```

---

## 6. Celery Task Inspection

### Check active tasks

```bash
docker compose -f docker-compose.staging.yml exec celery-worker \
  celery -A vitali inspect active
```

### Check scheduled tasks (Beat)

```bash
docker compose -f docker-compose.staging.yml exec celery-worker \
  celery -A vitali inspect scheduled
```

### Ping all workers

```bash
docker compose -f docker-compose.staging.yml exec celery-worker \
  celery -A vitali inspect ping --timeout 5
# Expected: {"celery@...": {"ok": "pong"}}
```

### Purge a queue (stuck tasks — use with caution)

```bash
# List queue lengths first
docker compose -f docker-compose.staging.yml exec celery-worker \
  celery -A vitali inspect reserved

# Purge the default queue
docker compose -f docker-compose.staging.yml exec celery-worker \
  celery -A vitali purge
```

### Retry a failed task by ID (from Flower or logs)

```bash
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py shell -c "
from celery.result import AsyncResult
r = AsyncResult('task-id-here')
print(r.state, r.result)
"
```

---

## 7. Common Incidents

### Symptom: 503 from Nginx, django container not healthy

```bash
# 1. Check container status
docker compose -f docker-compose.staging.yml ps

# 2. Check recent logs
docker compose -f docker-compose.staging.yml logs --tail=50 django

# 3. Restart
docker compose -f docker-compose.staging.yml restart django

# 4. If still unhealthy, check DB connectivity
docker compose -f docker-compose.staging.yml exec django \
  python manage.py dbshell -- -c "SELECT 1"
```

### Symptom: Celery tasks not processing

```bash
# 1. Ping workers
docker compose -f docker-compose.staging.yml exec celery-worker \
  celery -A vitali inspect ping

# 2. Check Redis
docker compose -f docker-compose.staging.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" ping

# 3. Restart worker
docker compose -f docker-compose.staging.yml restart celery-worker
```

### Symptom: WhatsApp webhooks not processing

```bash
# 1. Check Evolution API container
docker compose -f docker-compose.staging.yml logs --tail=30 evolution-api

# 2. Verify webhook secret matches
docker compose -f docker-compose.staging.yml exec django \
  python manage.py shell -c "from django.conf import settings; print(settings.WHATSAPP_WEBHOOK_SECRET[:4])"

# 3. Restart Evolution API
docker compose -f docker-compose.staging.yml restart evolution-api
```

### Symptom: Login returning 429 (too many requests)

```bash
# Clear the throttle key for the affected IP or user (see Redis section above)
# Or temporarily raise the rate in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
# and restart django — do NOT leave it raised permanently
```

---

*Vitali — docs/RUNBOOK.md*
