#!/usr/bin/env bash
# Vitali — Production Secret Generator
# ─────────────────────────────────────────────────────────────────────────────
# Generates strong values for every required production secret and prints a
# ready-to-fill secrets.env template. Run once per environment; store the output
# OUTSIDE the repo (host-only, /etc/vitali/secrets.env, root:root 0600) — see
# docs/SECRETS.md.
#
# Usage:
#   bash scripts/gen_secrets.sh > /etc/vitali/secrets.env && chmod 600 /etc/vitali/secrets.env
#
# Requires: openssl. SECRET_KEY/FIELD_ENCRYPTION_KEY use Python (Django/cryptography)
# when available, falling back to openssl-derived values that satisfy the boot checks.
set -euo pipefail

rand() { openssl rand -base64 "${1:-36}" | tr -d '\n/+=' | cut -c1-"${2:-48}"; }

# Django SECRET_KEY — prefer Django's own generator (matches its alphabet/entropy).
if command -v python3 >/dev/null 2>&1 && python3 -c "import django" >/dev/null 2>&1; then
  SECRET_KEY="$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
else
  SECRET_KEY="$(rand 50 64)"
fi

# FIELD_ENCRYPTION_KEY — must be a urlsafe-base64 32-byte Fernet key.
if command -v python3 >/dev/null 2>&1 && python3 -c "import cryptography" >/dev/null 2>&1; then
  FIELD_ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
else
  FIELD_ENCRYPTION_KEY="$(openssl rand -base64 32 | tr '+/' '-_')"
fi

POSTGRES_PASSWORD="$(rand 36 48)"
REDIS_PASSWORD="$(rand 36 48)"
WHATSAPP_EVOLUTION_API_KEY="$(rand 36 48)"
BACKUP_ENCRYPTION_KEY="$(rand 36 48)"
FLOWER_PASSWORD="$(rand 24 32)"

cat <<EOF
# Vitali production secrets — generated $(date -u +%FT%TZ)
# Store host-only (0600), NEVER commit. See docs/SECRETS.md.

# ── Django / DB / cache (validated fail-fast at boot) ───────────────────────
SECRET_KEY=${SECRET_KEY}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
REDIS_PASSWORD=${REDIS_PASSWORD}
FIELD_ENCRYPTION_KEY=${FIELD_ENCRYPTION_KEY}
WHATSAPP_EVOLUTION_API_KEY=${WHATSAPP_EVOLUTION_API_KEY}

# ── Backups (offsite + at-rest encryption) ──────────────────────────────────
# Back up BACKUP_ENCRYPTION_KEY in an offline vault — losing it makes every
# encrypted dump unrecoverable.
BACKUP_ENCRYPTION_KEY=${BACKUP_ENCRYPTION_KEY}
# Fill these from your S3/B2 provider to enable offsite uploads:
# BACKUP_S3_BUCKET=
# BACKUP_S3_ENDPOINT=
# BACKUP_S3_PREFIX=vitali
# BACKUP_S3_ACCESS_KEY=
# BACKUP_S3_SECRET_KEY=

# ── Monitoring ──────────────────────────────────────────────────────────────
# Flower basic-auth (user:password). Change the user if you like.
FLOWER_BASIC_AUTH=admin:${FLOWER_PASSWORD}
# Sentry (strongly recommended in prod; boot warns if empty):
# SENTRY_DSN=
# NEXT_PUBLIC_SENTRY_DSN=

# ── Payments (validated only if the billing/payments feature is enabled) ────
# MP_ACCESS_TOKEN=
# ASAAS_API_KEY=
EOF
