# Vitali — Deployment Guide> Staging and production deployment procedures, environment variables, and rollback instructions.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Access to GHCR (`docker login ghcr.io` with a GitHub PAT with `read:packages`)
- SSH access to the staging server (`/opt/vitali/` as working directory)
- GitHub repository secrets configured (see table below)

---

## Quickstart — Staging (first deploy)

```bash
# 1. Clone the repository on the staging server
git clone https://github.com/tropeks/Vitali.git /opt/vitali
cd /opt/vitali

# 2. Copy and fill in environment variables
cp .env.staging.example .env.staging
# Edit .env.staging — fill in EVERY value marked "change-me"
# See "Environment Variables" table below for full reference

# 3. Log in to GHCR to pull images
echo $GITHUB_TOKEN | docker login ghcr.io -u tropeks --password-stdin

# 4. Pull images (first time uses :latest tag)
GHCR_REPO=tropeks IMAGE_TAG=latest \
  docker compose -f docker-compose.staging.yml pull

# 5. Start services
GHCR_REPO=tropeks IMAGE_TAG=latest \
  docker compose -f docker-compose.staging.yml up -d

# 6. Run database migrations
docker compose -f docker-compose.staging.yml exec django \
  python manage.py migrate_schemas --shared --noinput

# 7. Collect static files
docker compose -f docker-compose.staging.yml exec django \
  python manage.py collectstatic --noinput

# 8. Create the first platform superuser
docker compose -f docker-compose.staging.yml exec django \
  python manage.py createsuperuser

# 9. Run smoke tests to verify
BASE_URL=https://staging.vitali.com.br \
COMPOSE_FILE=docker-compose.staging.yml \
COMPOSE_ENV_FILE=.env.staging \
  bash scripts/smoke_test.sh
```

Subsequent deploys are handled automatically by `.github/workflows/deploy-staging.yml` on every push to `master`.

---

## Reference Catalogs (TUSS / ANVISA / SIGTAP / CID-10 / CNES / CBO / CID-O / UCUM)

**These are NOT loaded by any migration, fixture, workflow, or entrypoint.** A
clean deploy boots with every governed catalog empty, and B6-B9 billing
(TUSS/ANVISA/SIGTAP-dependent) then fails **silently** — no error, just "sem
TUSS correspondente" at INFO level and the line never gets billed. Do this
once per environment (and again whenever refreshing a catalog to a newer
competência):

```bash
# 1. Run the ETL for each catalog you need (downloads + transforms the
#    official source into the CSV import_* expects). See scripts/catalogs/README.md
#    for the exact source URL, gotchas and expected row count per catalog —
#    do not skip that doc, several sources have non-obvious encoding/format traps.
cd scripts/catalogs && python3 etl_tuss.py && python3 etl_anvisa.py anvisa_medicamentos.csv
# ... one etl_<x>.py per catalog (cid10, cbo, sigtap, cido, ucum, anvisa_cmed, cnes)

# 2. Import into the target environment (idempotent upsert — safe to re-run;
#    --dry-run first is recommended for the multi-hour ones like CNES)
docker compose -f docker-compose.staging.yml exec django \
  python manage.py import_tuss --file /path/to/tuss_full.csv --tuss-version 202607
# ... one import_<x> per catalog — commands and required flags in scripts/catalogs/README.md

# 3. Gate: fail loudly (exit 1) if anything essential is still empty
docker compose -f docker-compose.staging.yml exec django \
  python manage.py verify_catalogs
```

`verify_catalogs` (`apps/core/management/commands/verify_catalogs.py`) is
read-only and reports every essential catalog's row count; it is the
actionable version of the `core.E008` system check
(`apps/core/checks.py`, `deploy=True`) — E008 only fires under `manage.py
check --deploy`, which today is **not run by any CI workflow** (same gap as
`core.E002`, documented in
`docs/research/VITALI_HUMAN_APPLIED_GATES.md` item 0.3 — applying that item
also activates E008, no separate CI change needed for the check itself).

**What belongs in CI/deploy automation but isn't wired yet (human lot):**
`verify_catalogs` cannot run as a CI *workflow* step — GitHub Actions runners
have no access to the multi-hundred-MB catalog source files staged on the
deploy host, and the import step itself is host-side for the same reason
(CNES alone is ~45MB processed / ~40min import). The right automation is a
**post-deploy step on the host** (e.g. appended to whatever script
`deploy-staging.yml` SSHes in and runs after `migrate_schemas`), not a GitHub
Actions job: `python manage.py verify_catalogs || <alert/rollback>`. This
repo does not touch `.github/workflows/` (denylist) or the host's deploy
script from an agent session — apply manually.

---

## Beta via Cloudflare Tunnel (no public host required)

Field-tested recipe (first run: 2026-07-21, `vitali.qtec.me` on a homelab PVE box)
for exposing a beta from any box with outbound internet — no port-forwarding, no
public IP. Pain points found on the way are called out inline so the next person
doesn't rediscover them.

### 1. Stack

Run the standard staging compose under an isolated project name so it can coexist
with a dev stack, with a host-local override file (never committed) for anything
host-specific — e.g. remapping nginx's published port when 80 is taken:

```bash
docker compose -p vitali-staging \
  -f docker-compose.staging.yml -f ~/vitali-staging-local.yml \
  --env-file .env.staging up -d
```

`.env.staging` gotchas (beyond the `.env.staging.example` comments):
- `ALLOWED_HOSTS` needs every public host **and** the tenant hosts
  (a leading-dot entry like `.example.com` covers one level of subdomains).
- `CSRF_TRUSTED_ORIGINS` likewise, with `https://` prefixes.
- `.env.staging` is gitignored — keep the real file on the host only.

> **PAIN (fixed):** `vitali/settings/production.py` used to lose the
> `django_tenants.postgresql_backend` engine when applying `DATABASE_URL`
> (`env.db()` emits its own `ENGINE` key), crashing `migrate_schemas` with
> `'DatabaseWrapper' object has no attribute 'set_schema'`. It was latent for
> weeks because no host had ever booted the production settings module. Fixed
> by re-pinning the engine after the update.

### 2. Database bootstrap

```bash
docker compose -p vitali-staging ... exec django python manage.py migrate_schemas --shared
BOOTSTRAP_ADMIN_PASSWORD='<generated>' docker compose -p vitali-staging ... exec \
  -e BOOTSTRAP_ADMIN_PASSWORD django python manage.py bootstrap_beta \
  --public-domain vitali.example.com \
  --clinic-slug demo --clinic-domain vitali-demo.example.com \
  --admin-email admin@demo.example.com
```

`bootstrap_beta` is idempotent (public tenant + domain, clinic tenant + domain,
default roles, clinic admin). It replaces the `manage.py shell -c` blobs that
used to live only in the CI workflow.

### 3. Tunnel + DNS

Add ingress rules to the tunnel config (`/etc/cloudflared/config.yml`) pointing
every public hostname at the nginx port, `cloudflared tunnel ingress validate`,
restart the service, then create one **proxied CNAME per hostname** targeting
`<tunnel-id>.cfargotunnel.com` (via `cloudflared tunnel route dns` — requires
the origin `cert.pem` from `cloudflared tunnel login` — or manually in the
Cloudflare dashboard).

> **PAIN (constraint, not a bug):** Cloudflare's free universal certificate
> only covers **one** subdomain level (`*.example.com`). A tenant at
> `demo.vitali.example.com` gets TLS handshake failures at the edge. For betas
> under a shared zone, put tenants on first-level hosts (`vitali-demo.example.com`)
> and register that as the tenant's `Domain` row — `bootstrap_beta
> --clinic-domain` exists for exactly this. (Paid plans can use Advanced
> Certificate Manager / Total TLS instead.)

> **PAIN (self-serve signup caveat):** tenant provisioning derives new tenant
> domains from the request host (`<slug>.<host>`), so self-serve signups on a
> tunneled beta will mint second-level hosts with the TLS limitation above.
> Fine for testing the flow itself; add DNS + a first-level `Domain` row per
> tenant you actually want to use.

### 4. Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://vitali.example.com/login          # 200
curl -s -o /dev/null -w '%{http_code}\n' https://vitali-demo.example.com/login    # 200
```

Cloudflare error cheat-sheet seen during setup: **530** = hostname's DNS record
doesn't target this tunnel (missing/wrong CNAME); **502** = tunnel fine, origin
port wrong or app down; TLS handshake failure = the wildcard-depth constraint
above.

---

## Release Pipeline — Image Publication

A semver tag builds and publishes backend, frontend, and viewer images to GHCR. GitHub Actions never connects to the PVE host and has no deployment credentials.

Deployment is run locally on the PVE host with the explicit Compose project and env file. Use the desired immutable image tag, then run shared and tenant migrations and the smoke test.

```bash
IMAGE_TAG=sha-<commit> GHCR_REPO=tropeks docker compose -p vitali-staging --env-file .env.staging -f docker-compose.staging.yml pull
IMAGE_TAG=sha-<commit> GHCR_REPO=tropeks docker compose -p vitali-staging --env-file .env.staging -f docker-compose.staging.yml up -d
docker compose -p vitali-staging --env-file .env.staging -f docker-compose.staging.yml exec -T django python manage.py migrate_schemas --shared --noinput
docker compose -p vitali-staging --env-file .env.staging -f docker-compose.staging.yml exec -T django python manage.py migrate_schemas --tenant --noinput
COMPOSE_PROJECT_NAME=vitali-staging COMPOSE_FILE=docker-compose.staging.yml COMPOSE_ENV_FILE=.env.staging BASE_URL=https://vitali.qtec.me bash scripts/smoke_test.sh
```

## Environment Variables

All variables must be set in `.env.staging` (and GitHub Secrets for the CI pipeline).

| Variable | Required | Example | Source |
|----------|----------|---------|--------|
| `SECRET_KEY` | ✅ | `python -c "import secrets; print(secrets.token_urlsafe(50))"` | Generate locally |
| `ENVIRONMENT` | ✅ | `staging` | Set manually |
| `DEBUG` | ✅ | `False` | Always False in staging |
| `ALLOWED_HOSTS` | ✅ | `staging.vitali.com.br,localhost` | Your staging domain |
| `CSRF_TRUSTED_ORIGINS` | ✅ | `https://staging.vitali.com.br` | Your staging domain with https:// |
| `POSTGRES_DB` | ✅ | `vitali` | Fixed |
| `POSTGRES_USER` | ✅ | `vitali` | Fixed |
| `POSTGRES_PASSWORD` | ✅ | Strong random string | Generate locally |
| `DATABASE_URL` | ✅ | `postgres://vitali:PASSWORD@postgres:5432/vitali` | Derived from above |
| `REDIS_PASSWORD` | ✅ | Strong random string | Generate locally |
| `REDIS_URL` | ✅ | `redis://:PASSWORD@redis:6379/0` | Derived from above |
| `GHCR_REPO` | ✅ | `tropeks` | GitHub package owner |
| `IMAGE_TAG` | ✅ | `sha-abc1234` or `latest` | Set by CI |
| `FIELD_ENCRYPTION_KEY` | ✅ | Base64 Fernet key | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SENTRY_DSN` | ✅ | `https://...@sentry.io/...` | Sentry project settings |
| `NEXT_PUBLIC_SENTRY_DSN` | ✅ | Same as SENTRY_DSN | Sentry project settings |
| `EMAIL_HOST_PASSWORD` | ✅ | `SG.xxxx` | SendGrid API key |
| `DEFAULT_FROM_EMAIL` | ✅ | `noreply@vitali.com.br` | Set manually |
| `NEXT_PUBLIC_API_URL` | ✅ | `https://staging.vitali.com.br` | Staging domain |
| `ANTHROPIC_API_KEY` | ✅ | `sk-ant-...` | Anthropic Console |
| `FEATURE_AI_TUSS` | — | `True` | Optional — enables AI TUSS coding |
| `WHATSAPP_EVOLUTION_URL` | ✅ | `http://evolution-api:8080` | Fixed (internal) |
| `WHATSAPP_EVOLUTION_API_KEY` | ✅ | Strong random string | Set manually |
| `WHATSAPP_WEBHOOK_SECRET` | ✅ | Strong random string | Set manually — must match Evolution API config |
| `ORTHANC_USERNAME` | ✅ | Strong random string | Set manually — basic-auth user shared by the `orthanc` service and `django`/`celery-worker` |
| `ORTHANC_PASSWORD` | ✅ | Strong random string | Set manually — basic-auth password, same as above |
| `ORTHANC_WEBHOOK_SECRET` | ✅ | Strong random string | Set manually — webhook refuses (`503`) unauthenticated when unset, see docs/IMAGING.md |
| `ORTHANC_URL` | — | `http://orthanc:8042` | **Not** read from this file — hardcoded in `docker-compose.staging.yml`'s `django`/`celery-worker` (Onda 2 / item 2.9) |

> **Fail-fast validation:** production startup now **rejects** empty or placeholder
> values for `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
> `WHATSAPP_EVOLUTION_API_KEY`, and `FIELD_ENCRYPTION_KEY` (e.g. `change-me`, `vitali`,
> the dev defaults, or the all-zero Fernet key). A deploy with any of these unset or
> left at a placeholder will refuse to boot. See [SECRETS.md](./SECRETS.md). Generate
> real values for every row above before first boot.

### Backups & TLS

- **Automated DB backups** run via the optional `db-backup` profile:
  `docker compose -f docker-compose.staging.yml --profile backup up -d`. Daily pg_dump
  to the `backups` volume, retention `BACKUP_KEEP_LAST` (default 7). See
  [BACKUPS.md](./BACKUPS.md) — configure an offsite (S3) copy for production.
- **TLS** is served by `docker/nginx/ssl.conf` (a `:443` server + HTTP→HTTPS redirect),
  enabled once certs are mounted under `/etc/nginx/ssl/`. See [TLS.md](./TLS.md).

### GitHub Actions boundary

No host, SSH key, runtime environment, or deployment secret belongs in GitHub. Actions only receives its repository token to publish GHCR images. Runtime secrets stay in `.env.staging` on the PVE host.

### Static compose config guard

`bash scripts/check_orthanc_config.sh` (Onda 2 / item 2.9) is a fast, Docker-free
static check: it fails if any `docker-compose*.yml` defines an `orthanc` service
without a non-empty `ORTHANC_URL` on its `django`/`celery-worker` siblings — the
exact class of regression this item fixed (imaging silently inert). Cheap enough
to run as a pre-commit/pre-deploy step; this repo does not wire it into
`.github/workflows/` itself (denylist — apply manually if you want it gating PRs).

---

## Rollback Procedure

### Manual rollback

```bash
cd /opt/vitali

# 1. Restore images tagged :rollback (set before the last deploy)
BACKEND_IMG="ghcr.io/tropeks/vitali-backend"
FRONTEND_IMG="ghcr.io/tropeks/vitali-frontend"
docker tag "${BACKEND_IMG}:rollback" "${BACKEND_IMG}:latest"
docker tag "${FRONTEND_IMG}:rollback" "${FRONTEND_IMG}:latest"

# 2. Restart with restored images
docker compose -f docker-compose.staging.yml up -d

# 3. Verify recovery
BASE_URL=https://staging.vitali.com.br \
COMPOSE_FILE=docker-compose.staging.yml \
COMPOSE_ENV_FILE=.env.staging \
  bash scripts/smoke_test.sh
```

### Rollback to a specific image tag

```bash
# List available tags (requires ghcr.io access)
IMAGE_TAG=sha-abc1234 GHCR_REPO=tropeks \
  docker compose -f docker-compose.staging.yml pull

IMAGE_TAG=sha-abc1234 GHCR_REPO=tropeks \
  docker compose -f docker-compose.staging.yml up -d
```

---

## Post-Deploy Verification

Beyond `smoke_test.sh`, confirm:

1. Sentry received a deploy notification (Sentry → Releases → check version)
2. JSON logs are structured: `docker compose logs django | head -5 | python3 -m json.tool`
3. Celery tasks are running: `docker compose exec django celery -A vitali inspect active`
4. Migrations applied: `docker compose exec django python manage.py showmigrations | grep "\[ \]"` should be empty
5. Essential catalogs loaded (see "Reference Catalogs" above): `docker compose exec django python manage.py verify_catalogs`

---

## Production Promotion

When staging is validated and a clinic pilot is signed:

1. Provision a production VPS (Hetzner CX42 recommended: 8 vCPU, 16GB RAM)
2. Repeat quickstart steps 1-9 with production values
3. Point DNS to production server
4. Configure TLS (Let's Encrypt via certbot or Cloudflare proxy)
5. Run `migrate_schemas` — see `docs/TENANT_MIGRATIONS.md` for the safe procedure

*Vitali — docs/DEPLOY.md*
