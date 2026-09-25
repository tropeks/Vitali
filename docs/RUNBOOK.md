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

## 8. Audit Trail (`core_auditlog`) Operations

Background: `core_auditlog` is the LGPD art. 37 / CFM 1.821/2007 trail, append-only
in the database, partitioned by month × tenant with a DEFAULT partition at both
levels (order 020). Retention is **240 months per tenant, purge off by default**
(order 021). The decision, the legal basis and the lock plan are in
[`docs/adr/ADR-0001-retencao-auditoria-20-anos.md`](adr/ADR-0001-retencao-auditoria-20-anos.md);
the control summary is in `docs/SECURITY.md` §3.6.

### Alarm: rows in a DEFAULT partition

`ensure_audit_partitions` runs after every `migrate_schemas` and daily via Celery Beat
(`core.ensure_audit_partitions`, 00:15 `America/Sao_Paulo`). When it finds rows in a
DEFAULT leaf it logs a `WARNING` (`core_auditlog: N linha(s) em folha(s) DEFAULT
(partição faltando)`) and prints `ALERTA: …`. That means **a partition is missing**,
not normal operation. Nothing is lost — DEFAULT accepts every write — but those rows
are outside per-tenant retention until moved.

```bash
# Find it in the logs
docker compose -f docker-compose.staging.yml logs celery-worker django \
  | grep "folha(s) DEFAULT"

# Measure (dry-run is the default — touches nothing)
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py backfill_audit_partitions
```

Then follow `docs/TENANT_MIGRATIONS.md` → "When the DEFAULT alarm fires". Typical
causes: a tenant provisioned mid-month before the daily run, or Celery Beat down
across a month boundary (check `celery -A vitali inspect scheduled`, §6).

### `purge_audit_logs` — never enable without an order

```bash
# Dry-run (the default): per tenant, reports what it WOULD drop, exits 0
docker compose -f docker-compose.staging.yml exec -T django \
  python manage.py purge_audit_logs
```

- Without `--execute` it changes nothing. **Do not run `--execute`, and do not set
  `TenantAuditRetention.purge_enabled=True` for any tenant, without an explicit
  order from the Imediato.** Staging and production are not touched by orders
  020/021.
- Even when enabled, it only drops a tenant's dedicated partition older than
  `retention_months`, never a DEFAULT partition, never with `DELETE`, and
  `drop_partition` refuses without a verified cold-export receipt.
- Cold copies go to `AUDIT_LOG_COLD_STORAGE_DIR` on local disk
  (`LocalDiskColdStorageBackend`). There is **no** S3/Glacier backend yet.
- **`core_auditlog_pre020`** (the pre-partitioning table) stays. No `DROP` without the
  Imediato's explicit acceptance.

---

## Monitoring & alerting

| Tool | Where | What it watches | How to reach |
|------|-------|-----------------|--------------|
| **Sentry** | SaaS (`SENTRY_DSN`) | Backend + Celery exceptions, releases | sentry.io project dashboard |
| **Flower** | `flower` service, `127.0.0.1:5555` | Celery tasks: active/queued, failures, retries | SSH tunnel: `ssh -L 5555:127.0.0.1:5555 host`; basic auth = `FLOWER_BASIC_AUTH` |
| **Uptime Kuma** | `uptime-kuma` service, `127.0.0.1:3001` | External reachability of `/health/` + public frontend | SSH tunnel: `ssh -L 3001:127.0.0.1:3001 host`; configure monitors on first boot |

**Recommended Sentry alert rules:** new issue → notify; error rate spike (>N/min)
→ notify; failed Celery task → notify. Configure under the project's Alerts.

**Retry a failed task** (id from Flower or logs):
```bash
docker compose exec celery-worker python -c "from vitali.celery import app; app.tasks['<name>'].apply_async(args=[...])"
```

## Disaster recovery (DR)

Targets: **RPO 24h, RTO 4h**. Backups: daily 02:00 UTC, encrypted + offsite (see
`docs/BACKUPS.md`). Always confirm the latest restore drill (`scripts/restore_test.sh`)
was green before relying on a backup.

### Scenario: host lost (VPS dead / unrecoverable)

1. Provision a new host (Hetzner CX42 or equivalent), install Docker.
2. Clone the repo to `/opt/vitali`; place `/etc/vitali/secrets.env` (from your vault).
3. Pull the latest backup: `BACKUP_S3_BUCKET=… … bash scripts/restore_test.sh` first to
   verify it restores, then restore for real into the prod Postgres volume.
4. `docker compose -f docker-compose.prod.yml --env-file /etc/vitali/secrets.env up -d`.
5. Re-issue TLS (`docs/TLS.md`), point DNS, run `scripts/smoke_test.sh`.

### Scenario: DB corruption (host alive)

1. Stop django + celery (keep postgres): `docker compose stop django celery-worker celery-beat`.
2. Snapshot the current (corrupt) volume before touching it — never restore over the
   only copy.
3. Restore the latest good dump into a fresh DB (procedure in `docs/BACKUPS.md`).
4. Restart app services; smoke test.

### Scenario: secret leaked (e.g. SECRET_KEY / DB password)

1. Rotate the leaked secret in `/etc/vitali/secrets.env` (`scripts/gen_secrets.sh` for
   fresh values).
2. **Never rotate `FIELD_ENCRYPTION_KEY` blindly** — rotating it without re-encrypting
   makes existing PHI unreadable. Follow a key-rotation migration, not a swap.
3. Recreate affected services; force-logout sessions if `SECRET_KEY` changed
   (sessions/tokens become invalid automatically).

---

## Wedge Activation

For instructions on activating Wedges (Pilot), please see the [Wedge Activation Runbook](WEDGE_ACTIVATION.md).

---

*Vitali — docs/RUNBOOK.md*
