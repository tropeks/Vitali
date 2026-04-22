"""
Vitali — Production Settings
"""

import environ

from .base import *  # noqa: F401, F403

env = environ.Env()

DEBUG = False
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
ENVIRONMENT = env("ENVIRONMENT", default="production")

# ─── Security headers ─────────────────────────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Upload size limits (protect against large payload DoS)
# S-073: raised to 25 MB to accommodate Whisper audio uploads
DATA_UPLOAD_MAX_MEMORY_SIZE = 26_214_400  # 25 MB for Whisper audio upload
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB

# ─── Database — connection pooling ───────────────────────────────────────────
# CONN_MAX_AGE=60: Django reuses PG connections for up to 60s per thread,
# cutting per-request connection overhead from ~5ms to ~0ms after warmup.
# CONN_HEALTH_CHECKS=True: health-checks the connection before reuse so stale
# connections (idle beyond PG's tcp_keepalives_idle) are detected and reopened.
#
# NOTE: .update() not = to preserve ENGINE=django_tenants.postgresql_backend from base.py.
# Replacing DATABASES entirely would break multi-tenancy.
DATABASES["default"].update(env.db("DATABASE_URL"))  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# ─── Cache — Redis (django-redis) ────────────────────────────────────────────
# Uses django_redis.cache.RedisCache (not the Django built-in) because we need
# CLIENT_CLASS and the richer connection pool options. KEY_PREFIX isolates
# this app's keys in a shared Redis instance.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://redis:6379/0"),
        "KEY_PREFIX": "vitali",
        "TIMEOUT": 300,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# ─── Sessions — Redis-backed ──────────────────────────────────────────────────
# Avoids DB session reads on every authenticated request.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# ─── Static files — Whitenoise ────────────────────────────────────────────────
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ─── Email ────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@vitali.com.br")

# ─── Structured JSON Logging ──────────────────────────────────────────────────
# Overrides base.py plain-text format. Every log line is a JSON object with
# tenant + request_id injected by TenantLogFilter / RequestIdMiddleware.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "tenant_request": {
            "()": "apps.core.middleware.TenantRequestLogFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s %(tenant)s %(request_id)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["tenant_request"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ─── Sentry ───────────────────────────────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    def _sentry_before_send(event, hint):
        """
        1. Tag event with the current tenant schema (for triage by clinic).
        2. Strip PHI fields to comply with LGPD — patient data must not reach
           Sentry's US servers. send_default_pii=False suppresses headers/cookies
           but NOT custom extra/user fields added by other code.
        """
        try:
            from django.db import connection

            tenant = getattr(connection, "tenant", None)
            if tenant:
                event.setdefault("tags", {})["tenant"] = tenant.schema_name
        except Exception:
            pass

        # Strip known PHI fields from event extras and user context
        _PHI_KEYS = {"cpf", "patient_id", "patient_name", "phone", "email"}
        if "user" in event:
            event["user"] = {k: v for k, v in event["user"].items() if k not in _PHI_KEYS}
        if "extra" in event:
            event["extra"] = {k: v for k, v in event["extra"].items() if k not in _PHI_KEYS}

        return event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,
        before_send=_sentry_before_send,
    )
