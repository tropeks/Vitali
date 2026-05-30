"""
Production startup validators called from vitali/settings/production.py.

Kept in a standalone module so unit tests can import without triggering the
full production settings load (which requires SECRET_KEY, ALLOWED_HOSTS, etc.).
"""

_FERNET_ZERO_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


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
            "Generate a key: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
