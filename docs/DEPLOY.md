# Vitali — Deployment Guide

> Staging and production deployment procedures, environment variables, and rollback instructions.

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

## Release Pipeline — Semver Tag Deploy (staging → prod)

Tagged releases run an end-to-end deploy with **zero manual SSH** via
`.github/workflows/release-deploy.yml`. Pushing a `v*.*.*` tag:

```bash
git tag v1.4.0
git push origin v1.4.0
```

triggers, in order:

1. **build-and-push** — builds the backend + frontend images and pushes them to
   GHCR tagged with both the semver (`v1.4.0`) and the commit SHA (`sha-<sha>`).
   Always runs, so released images land in GHCR even before any host is wired up.
2. **deploy-staging** — pulls `IMAGE_TAG=v1.4.0` on the staging host, rolls the
   stack, runs migrations + `collectstatic`, and runs `smoke_test.sh`. On failure
   it auto-rolls-back to the previously running images (aliased `:rollback`).
3. **deploy-production** — same flow against the production host using
   `docker-compose.prod.yml`, **gated behind manual approval** (see below).

The deploy jobs are dormant until their host is provisioned: set the repo
variables `STAGING_ENABLED` / `PROD_ENABLED` to `"true"` (Settings → Secrets and
variables → Actions → Variables) to enable each one.

### Manual approval for production

Production promotion is gated by a GitHub **Environment**, not a code change:

1. Settings → Environments → **production** → add **Required reviewers**.
2. When a release reaches `deploy-production`, GitHub pauses the job and requests
   approval from a reviewer before any step runs. This is the "prod via aprovação
   manual" gate — no SSH, no manual `docker` commands.

### Release secrets & variables

In addition to the staging secrets above, the `production` environment needs:

| Secret | Purpose |
|--------|---------|
| `PROD_SSH_KEY` | Private key for SSH to the production server |
| `PROD_HOST` | Production server IP or hostname |
| `PROD_USER` | SSH username |
| `PROD_BASE_URL` | Full URL for smoke tests (e.g. `https://vitali.com.br`) |

| Repo variable | Purpose |
|---------------|---------|
| `STAGING_ENABLED` | `"true"` enables the staging deploy job |
| `PROD_ENABLED` | `"true"` enables the production deploy job |

Both hosts must already be logged in to GHCR (`docker login ghcr.io`) and have the
repo checked out at `/opt/vitali` with their env files in place
(`.env.staging` for staging, `/etc/vitali/secrets.env` for prod — see
[SECRETS.md](./SECRETS.md)).

---

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

### GitHub Actions Secrets

The `deploy-staging.yml` workflow requires these secrets set in repository settings:

| Secret | Purpose |
|--------|---------|
| `STAGING_SSH_KEY` | Private key for SSH to staging server |
| `STAGING_HOST` | Staging server IP or hostname |
| `STAGING_USER` | SSH username (e.g. `ubuntu`) |
| `STAGING_BASE_URL` | Full URL for smoke tests (e.g. `https://staging.vitali.com.br`) |

All Django secrets from the `.env.staging` table above must also be present in the GitHub environment named `staging` (Settings → Environments → staging → secrets).

---

## Rollback Procedure

### Automatic rollback (via CI)

If smoke tests fail after a deploy, `deploy-staging.yml` automatically restores the previous images tagged `:rollback` and restarts services. Check GitHub Actions for the failure reason.

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

---

## Production Promotion

When staging is validated and a clinic pilot is signed:

1. Provision a production VPS (Hetzner CX42 recommended: 8 vCPU, 16GB RAM)
2. Repeat quickstart steps 1-9 with production values
3. Point DNS to production server
4. Configure TLS (Let's Encrypt via certbot or Cloudflare proxy)
5. Run `migrate_schemas` — see `docs/TENANT_MIGRATIONS.md` for the safe procedure

*Vitali — docs/DEPLOY.md*
