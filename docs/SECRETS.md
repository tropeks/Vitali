# Secrets Management

Vitali handles LGPD-regulated patient data. Every secret must be strong, unique, and
injected at runtime — never committed to version control.

## Required production secrets

| Variable | Purpose | How to generate |
|---|---|---|
| `SECRET_KEY` | Django cryptographic signing (sessions, CSRF, password-reset links) | `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `POSTGRES_PASSWORD` | Postgres database access | Use your secret manager's random-string generator (≥32 chars) |
| `REDIS_PASSWORD` | Redis cache / Celery broker authentication | Use your secret manager's random-string generator (≥32 chars) |
| `FIELD_ENCRYPTION_KEY` | Fernet encryption of LGPD PHI fields (CPF, etc.) at rest | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

All four are validated at startup by `vitali/settings/_security_checks.py`. The application
will refuse to start if any is missing, empty, or an obvious placeholder.

## Injection methods

### Docker secrets (recommended for self-hosted)

Docker Swarm secrets are mounted at `/run/secrets/<name>` and never written to the
container environment or image layers.

```yaml
# docker-compose.production.yml (excerpt)
services:
  django:
    secrets:
      - secret_key
      - postgres_password
      - redis_password
      - field_encryption_key
    environment:
      SECRET_KEY_FILE: /run/secrets/secret_key
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
      REDIS_PASSWORD_FILE: /run/secrets/redis_password
      FIELD_ENCRYPTION_KEY_FILE: /run/secrets/field_encryption_key

secrets:
  secret_key:
    external: true
  postgres_password:
    external: true
  redis_password:
    external: true
  field_encryption_key:
    external: true
```

Create each secret once:

```sh
echo "$(python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")" \
  | docker secret create secret_key -

openssl rand -base64 32 | docker secret create postgres_password -
openssl rand -base64 32 | docker secret create redis_password -

python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  | docker secret create field_encryption_key -
```

### Cloud secret managers

For cloud deployments, store each secret in your provider's secret manager and inject
at container startup via an init sidecar or the provider's native env-injection:

- **AWS**: Secrets Manager → ECS task definition `secrets` block
- **GCP**: Secret Manager → Cloud Run `--set-secrets` flag
- **Azure**: Key Vault → AKS CSI driver or Container Apps secrets

### Environment variables (last resort)

If your platform only supports plain environment variables, set them in your
platform's encrypted configuration store — never in a `.env` file checked into git.

## Rules

1. **Never commit `.env` files** containing real values. `backend/.env.production.example`
   is the only env file in version control and contains only placeholder markers.
2. **Never log secrets.** Django's `DEBUG=False` prevents the settings page from
   exposing them, and the JSON log formatter in `production.py` does not log env vars.
3. **Rotate on suspected exposure.** If a secret is accidentally logged, pushed to git,
   or otherwise exposed: rotate it immediately, then audit access logs.
4. **Separate secrets per environment.** Staging and production must use different
   values — never share a `FIELD_ENCRYPTION_KEY` between environments, or a staging
   compromise would expose production-encrypted PHI.
5. **Back up `FIELD_ENCRYPTION_KEY` securely.** Loss of this key makes all encrypted
   PHI columns permanently unreadable. Store a copy in an offline, access-controlled
   vault separate from the primary secret manager.
