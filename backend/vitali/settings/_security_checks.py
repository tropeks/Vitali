"""
Production startup validators called from vitali/settings/production.py.

Kept in a standalone module so unit tests can import without triggering the
full production settings load (which requires SECRET_KEY, ALLOWED_HOSTS, etc.).
"""

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
    ):
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a unique, unpredictable value in production. "
            "The current value is the development default or an obvious placeholder, "
            "which makes sessions, CSRF tokens, and password-reset links forgeable. "
            'Generate one: python -c "from django.core.management.utils import '
            'get_random_secret_key; print(get_random_secret_key())"'
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
