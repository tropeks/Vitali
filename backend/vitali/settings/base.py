"""
Vitali — Base Settings
Django 5.2 + django-tenants (schema-per-tenant)
"""
import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# ─── Django-Tenants ───────────────────────────────────────────────────────────
# Apps that live in the PUBLIC schema (shared across all tenants)
SHARED_APPS = [
    "django_tenants",          # must be first
    "apps.core",               # Tenant, Domain, Plan, Subscription, User, Role, FeatureFlag
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.postgres",  # SearchVectorField, GinIndex — required for TUSS fuzzy search
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django_celery_beat",      # global scheduler — must live in public schema
]

# Apps that live in each TENANT schema (per-clinic data isolation)
TENANT_APPS = [
    "apps.emr",
    "apps.analytics",
    "apps.billing",
    "apps.pharmacy",
    "apps.ai",
    "apps.whatsapp",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
]

INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

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
    "apps.core.middleware.CurrentUserMiddleware",
    "apps.core.middleware.FeatureFlagMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vitali.urls"
PUBLIC_SCHEMA_URLCONF = "vitali.urls_public"

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
