"""
Production startup validators called from vitali/settings/production.py.

Kept in a standalone module so unit tests can import without triggering the
full production settings load (which requires SECRET_KEY, ALLOWED_HOSTS, etc.).
"""

# Valid values for DEPLOYMENT_PROFILE (P3-01). Air-gap is explicitly out of scope
# for Romulo's cloud-only deployment model.
DEPLOYMENT_PROFILE_CHOICES = ("pool", "dedicated")

_FERNET_ZERO_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

# The default SECRET_KEY shipped in development.py — must never reach production.
_DEV_SECRET_KEY = "dev-insecure-key-change-in-production-vitali-2026"

# Obvious placeholder values that must be rejected for any secret.
_OBVIOUS_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "changeme",
        "change_me",
        "vitali",
        "password",
        "secret",
        "postgres",
        "redis",
    }
)


def assert_field_encryption_key(key: str) -> None:
    """Raise ImproperlyConfigured if *key* is empty or the all-zero Fernet placeholder.

    The placeholder is the default in base.py for development convenience; it must
    never reach production because it makes LGPD-regulated encrypted fields (CPF,
    etc.) trivially reversible by anyone with codebase access.
    """
    from django.core.exceptions import ImproperlyConfigured

    if not key or key == _FERNET_ZERO_KEY:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY must be set to a real Fernet key in production. "
            "The current value is the all-zero dev placeholder from base.py, which "
            "makes encrypted LGPD fields (CPF, etc.) trivially reversible. "
            'Generate a key: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )


def assert_secret_key(key: str) -> None:
    """Raise ImproperlyConfigured if SECRET_KEY is empty, the dev default, or an obvious placeholder.

    Django's SECRET_KEY is used for cryptographic signing of sessions, CSRF tokens,
    and password-reset links. Using the committed dev value or a trivial placeholder
    makes all of these trivially forgeable.
    """
    from django.core.exceptions import ImproperlyConfigured

    normalized = key.lower().strip()
    if (
        not key
        or key == _DEV_SECRET_KEY
        or normalized in _OBVIOUS_PLACEHOLDERS
        or normalized.startswith("django-insecure-")
        or normalized == "build-time-placeholder-not-used-in-production"
    ):
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a unique, unpredictable value in production. "
            "The current value is the development default or an obvious placeholder, "
            "which makes sessions, CSRF tokens, and password-reset links forgeable. "
            'Generate one: python -c "from django.core.management.utils import '
            'get_random_secret_key; print(get_random_secret_key())"'
        )


def assert_whatsapp_evolution_api_key(key: str) -> None:
    """Raise ImproperlyConfigured if WHATSAPP_EVOLUTION_API_KEY is empty or a placeholder.

    The Evolution API gateway authenticates inbound/outbound WhatsApp traffic with
    this key. Left empty or at the compose default ('change-me'), any caller that
    reaches the gateway can read or send patient messages.
    """
    from django.core.exceptions import ImproperlyConfigured

    if not key or key.lower().strip() in _OBVIOUS_PLACEHOLDERS:
        raise ImproperlyConfigured(
            "WHATSAPP_EVOLUTION_API_KEY must be set to a real value in production. "
            "The current value is empty or an obvious placeholder (e.g. 'change-me'). "
            "Inject it via Docker secrets or your cloud secret manager."
        )


def assert_postgres_password(password: str) -> None:
    """Raise ImproperlyConfigured if POSTGRES_PASSWORD is empty or an obvious dev placeholder.

    A weak or committed Postgres password gives any network-reachable attacker full
    read/write access to all tenant databases, including LGPD-regulated PHI.
    """
    from django.core.exceptions import ImproperlyConfigured

    if not password or password.lower().strip() in _OBVIOUS_PLACEHOLDERS:
        raise ImproperlyConfigured(
            "POSTGRES_PASSWORD must be set to a strong, unique value in production. "
            "The current value is empty or an obvious placeholder (e.g. 'vitali', 'change-me'). "
            "Inject it via Docker secrets or your cloud secret manager — never commit it to .env."
        )


def assert_redis_password(password: str) -> None:
    """Raise ImproperlyConfigured if REDIS_PASSWORD is empty or an obvious dev placeholder.

    An unauthenticated Redis instance exposes session data and Celery task payloads
    to any process that can reach the Redis port, including other containers in the
    same Docker network.
    """
    from django.core.exceptions import ImproperlyConfigured

    if not password or password.lower().strip() in _OBVIOUS_PLACEHOLDERS:
        raise ImproperlyConfigured(
            "REDIS_PASSWORD must be set to a strong, unique value in production. "
            "The current value is empty or an obvious placeholder (e.g. 'vitali', 'change-me'). "
            "Inject it via Docker secrets or your cloud secret manager — never commit it to .env."
        )


def assert_optional_secret_not_placeholder(name: str, value: str) -> None:
    """For secrets that are optional (a clinic may not use them) but must never be a
    placeholder when present.

    Empty → no-op (the feature is simply disabled). Non-empty placeholder → raise,
    because a half-configured integration (e.g. a payments token left at 'change-me')
    fails confusingly at runtime instead of loudly at boot.
    """
    from django.core.exceptions import ImproperlyConfigured

    if value and value.lower().strip() in _OBVIOUS_PLACEHOLDERS:
        raise ImproperlyConfigured(
            f"{name} is set to an obvious placeholder. Either leave it empty to disable "
            f"the integration, or set it to a real value. Never ship a placeholder."
        )


def warn_if_missing_sentry(dsn: str) -> None:
    """Emit a non-fatal warning if SENTRY_DSN is empty in production.

    Sentry is the only error/crash visibility in production; running without it is
    allowed (e.g. an air-gapped pilot) but is almost always a misconfiguration, so we
    surface it loudly without blocking boot.
    """
    if not dsn:
        import warnings

        warnings.warn(
            "SENTRY_DSN is empty — production is running without error tracking. "
            "Set SENTRY_DSN (and NEXT_PUBLIC_SENTRY_DSN on the frontend) to capture "
            "crashes. Ignore only if observability is handled some other way.",
            stacklevel=2,
        )


def assert_worker_database_separation(role: str, database_url: str, celery_database_url: str) -> None:
    """Raise ImproperlyConfigured when a worker/beat process lacks a separate DB DSN.

    The least-privilege boundary for Celery workers is the **database credential**,
    not the encryption key — workers still require FIELD_ENCRYPTION_KEY because tasks
    read and write encrypted EMR fields (CPF, etc.). The worker Postgres role should
    have USAGE/SELECT/INSERT/UPDATE/DELETE across all tenant schemas (django-tenants
    switches search_path at runtime) but must NOT be a superuser or hold DDL privileges.

    Web role → always a no-op; this validator is a gate for worker|beat only.
    """
    if role not in ("worker", "beat"):
        return

    from django.core.exceptions import ImproperlyConfigured

    if not celery_database_url or celery_database_url == database_url:
        raise ImproperlyConfigured(
            "Workers and beat processes must use a separate, less-privileged Postgres DSN. "
            "Set CELERY_DATABASE_URL to a DSN for a dedicated Postgres role (e.g. "
            "postgres://vitali_worker:...@postgres:5432/vitali) that holds "
            "USAGE/SELECT/INSERT/UPDATE/DELETE on all tenant schemas but is NOT a superuser "
            "and holds no DDL privileges. "
            "CELERY_DATABASE_URL must be non-empty and distinct from the web tier's DATABASE_URL. "
            "Note: workers STILL need FIELD_ENCRYPTION_KEY — the least-privilege boundary "
            "is DB credentials, not the crypto key."
        )


def assert_deployment_profile(profile: str) -> None:
    """Raise ImproperlyConfigured if *profile* is not a recognised deployment profile.

    Valid choices are 'pool' (shared multi-tenant instance, the default) and
    'dedicated' (single-tenant isolated instance, foundation for the Fase 3 Tenant
    Operator). Air-gap is explicitly out of scope — Vitali is a cloud-only product
    (Romulo's cloud). Any other value — including empty string — is rejected at boot
    so misconfigured containers fail loudly rather than behaving unexpectedly.
    """
    from django.core.exceptions import ImproperlyConfigured

    if profile not in DEPLOYMENT_PROFILE_CHOICES:
        raise ImproperlyConfigured(
            f"DEPLOYMENT_PROFILE must be one of {list(DEPLOYMENT_PROFILE_CHOICES)} "
            f"(got {profile!r}). "
            "'pool' = shared multi-tenant instance (default); "
            "'dedicated' = single-tenant isolated instance (Fase 3 Tenant Operator). "
            "Air-gap is out of scope — Vitali runs on Romulo's cloud only."
        )
