"""
Vitali — Runtime secret resolution helpers.

This module is the single indirection point between Django settings and the
physical secret store. All callers read ``settings.FIELD_ENCRYPTION_KEY``;
none import this module directly. base.py calls ``resolve_field_encryption_key``
once at startup and assigns the result to that setting.

KMS/envelope seam
-----------------
A future ``FIELD_ENCRYPTION_KMS_*`` provider (e.g. AWS KMS, GCP CKMS, HashiCorp
Vault) slots in HERE — inside ``resolve_field_encryption_key`` — without
touching any call site. The precedence order will become:

    KMS provider (if configured)
        → FIELD_ENCRYPTION_KEY_FILE (Docker/Podman secret file)
            → FIELD_ENCRYPTION_KEY env var (dev/CI)
                → all-zero placeholder (local migrations only)

Currently only the file → env → placeholder path is implemented (P3-02).
"""

from pathlib import Path

from ._security_checks import _FERNET_ZERO_KEY


def resolve_field_encryption_key(env) -> str:
    """Return the FIELD_ENCRYPTION_KEY to assign in base.py.

    Precedence (highest wins):

    1. ``FIELD_ENCRYPTION_KEY_FILE`` — path to a file containing the key
       (e.g. a Docker secret at ``/run/secrets/field_encryption_key``).
       The file is read once at boot; its contents are stripped of leading/
       trailing whitespace so Docker-mounted secret files with a trailing
       newline work without manual trimming.
       **If the path is set but the file is missing or empty, boot fails
       loudly rather than silently falling back to a weaker key.**

    2. ``FIELD_ENCRYPTION_KEY`` env var — dev/CI convenience.  Works exactly
       as before P3-02 so no CI change is required.

    3. ``_FERNET_ZERO_KEY`` placeholder — allows ``cp .env.example .env &&
       python manage.py migrate`` to work out of the box for local
       development.  The production startup validator in production.py
       (``assert_field_encryption_key``) rejects this value so it can never
       reach a live environment.

    The *env* argument is the ``environ.Env`` instance created in base.py.
    Tests pass a ``_FakeEnv`` shim that exposes the same ``.str()`` interface,
    making every code path unit-testable without touching ``os.environ``.
    """
    from django.core.exceptions import ImproperlyConfigured

    key_file = env.str("FIELD_ENCRYPTION_KEY_FILE", default="")
    if key_file:
        p = Path(key_file)
        if not p.is_file():
            raise ImproperlyConfigured(
                f"FIELD_ENCRYPTION_KEY_FILE is set to {key_file!r} but no readable "
                "file exists at that path. The container may be missing the Docker "
                "secret mount, or the path is wrong. Refusing to fall back to the "
                "FIELD_ENCRYPTION_KEY env var to avoid silently using a weaker key. "
                "Fix the secret mount or unset FIELD_ENCRYPTION_KEY_FILE."
            )
        value = p.read_text().strip()
        if not value:
            raise ImproperlyConfigured(
                f"FIELD_ENCRYPTION_KEY_FILE is set to {key_file!r} but the file is "
                "empty or contains only whitespace. Provide a valid Fernet key or "
                "remove the file and unset FIELD_ENCRYPTION_KEY_FILE."
            )
        return value

    return env.str("FIELD_ENCRYPTION_KEY", default=_FERNET_ZERO_KEY)
