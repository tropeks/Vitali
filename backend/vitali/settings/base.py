"""
Vitali — Base Settings
Django 5.2 + django-tenants (schema-per-tenant)
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# ─── Django-Tenants ───────────────────────────────────────────────────────────
# Apps that live in the PUBLIC schema (shared across all tenants)
SHARED_APPS = [
    "django_tenants",  # must be first
    "apps.core",  # Tenant, Domain, Plan, Subscription, User, Role, FeatureFlag
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.postgres",  # SearchVectorField, GinIndex — required for TUSS fuzzy search
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django_celery_beat",  # global scheduler — must live in public schema
]

# Apps that live in each TENANT schema (per-clinic data isolation)
TENANT_APPS = [
    "apps.emr",
    "apps.analytics",
    "apps.billing",
    "apps.pharmacy",
    "apps.ai",
    "apps.whatsapp",
    "apps.hr",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = "core.Tenant"
TENANT_DOMAIN_MODEL = "core.Domain"
DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]

# ─── Auth ─────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "core.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Middleware ───────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # must be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.middleware.CurrentUserMiddleware",
    "apps.core.middleware.FeatureFlagMiddleware",
    "apps.core.middleware.MFARequiredMiddleware",  # S-062: blocks staff without mfa_verified JWT
    "apps.core.middleware.PasswordChangeRequiredMiddleware",  # S-076-NEW: blocks users with temp password
    "apps.core.middleware.DemoModeMiddleware",  # no-op unless DEMO_MODE=true
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vitali.urls"
PUBLIC_SCHEMA_URLCONF = "vitali.urls_public"

# Trust X-Forwarded-Host from Next.js server-side routes running inside Docker.
# Node.js fetch() cannot set the Host header (Fetch API spec forbids it), so
# the Next.js proxy routes forward the original browser Host via X-Forwarded-Host.
# Django's request.get_host() reads this header, which django-tenants uses to
# resolve the tenant schema.
USE_X_FORWARDED_HOST = True

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "vitali.wsgi.application"

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://vitali:vitali@localhost:5435/vitali",
    )
}
DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"

# ─── Password validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# ─── Internationalization ─────────────────────────────────────────────────────
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ─── Static files ─────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─── REST Framework ───────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.authentication.TenantJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    # Global rate limiting: anonymous (100/hour) and authenticated (1000/hour).
    # TenantUserRateThrottle prefixes cache key with schema to prevent cross-tenant
    # bucket collision. Login endpoint applies a tighter per-view override (5/min).
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "apps.core.throttles.TenantUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "login": "5/min",
    },
}

# ─── JWT ─────────────────────────────────────────────────────────────────────
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_BLACKLIST_SERIALIZER": "rest_framework_simplejwt.serializers.TokenBlacklistSerializer",
}

# ─── DRF Spectacular (OpenAPI) ────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "Vitali API",
    "DESCRIPTION": "Plataforma Hospitalar SaaS — ERP + EMR + AI",
    "VERSION": "0.2.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ─── Celery ───────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ─── Cache ────────────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/1"),
    }
}

# ─── Session ─────────────────────────────────────────────────────────────────
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# ─── Encryption (LGPD — campos sensíveis) ────────────────────────────────────
FIELD_ENCRYPTION_KEY = env(
    "FIELD_ENCRYPTION_KEY",
    default="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)

# ─── AI / LLM ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
AI_RATE_LIMIT_PER_HOUR = env.int("AI_RATE_LIMIT_PER_HOUR", default=100)
AI_SUGGEST_TIMEOUT_S = env.int("AI_SUGGEST_TIMEOUT_S", default=5)
FEATURE_AI_TUSS = env.bool("FEATURE_AI_TUSS", default=False)
FEATURE_AI_SCRIBE = env.bool("FEATURE_AI_SCRIBE", default=False)
FEATURE_WHISPER_FALLBACK = env.bool("FEATURE_WHISPER_FALLBACK", default=True)
SCRIBE_SESSION_RETENTION_DAYS = env.int("SCRIBE_SESSION_RETENTION_DAYS", default=90)

# ─── WhatsApp / Evolution API (S-032) ───────────────────────────────────────
WHATSAPP_EVOLUTION_URL = env("WHATSAPP_EVOLUTION_URL", default="http://evolution-api:8080")
WHATSAPP_EVOLUTION_API_KEY = env("WHATSAPP_EVOLUTION_API_KEY", default="")
WHATSAPP_WEBHOOK_SECRET = env("WHATSAPP_WEBHOOK_SECRET", default="")
WHATSAPP_INSTANCE_NAME = env("WHATSAPP_INSTANCE_NAME", default="vitali")
WHATSAPP_CLINIC_PHONE = env("WHATSAPP_CLINIC_PHONE", default="+5511999999999")

# ─── PIX / Asaas (S-055) ─────────────────────────────────────────────────────
ASAAS_API_KEY = env("ASAAS_API_KEY", default="")
ASAAS_WEBHOOK_TOKEN = env("ASAAS_WEBHOOK_TOKEN", default="")
ASAAS_ENVIRONMENT = env("ASAAS_ENVIRONMENT", default="sandbox")
PIX_CHARGE_EXPIRY_MINUTES = env.int("PIX_CHARGE_EXPIRY_MINUTES", default=30)

# ─── MFA — TOTP (S-062) ──────────────────────────────────────────────────────
MFA_GRACE_PERIOD_DAYS = env.int("MFA_GRACE_PERIOD_DAYS", default=30)

# ─── Prescription PDF (S-065) ────────────────────────────────────────────────
PRESCRIPTION_PDF_CACHE_TTL = env.int("PRESCRIPTION_PDF_CACHE_TTL", default=3600)

# billing/ migrations directory is root-owned (755). Redirect to writable package.
MIGRATION_MODULES = {
    "billing": "billing_migrations",
}

# ─── Demo Mode (S-043) ────────────────────────────────────────────────────────
# When True: all write operations return 403. Auth endpoints whitelisted.
# Set DEMO_MODE=true in .env for investor demos. Never enable in production.
DEMO_MODE = env.bool("DEMO_MODE", default=False)

# ─── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
