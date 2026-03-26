"""
Vitali — Development Settings
"""
from .base import *  # noqa: F401, F403
import environ

env = environ.Env()

DEBUG = True
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-in-production-vitali-2026")
ALLOWED_HOSTS = ["*"]

# Show all tenant schemas in development
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

# Django debug toolbar (opcional)
INTERNAL_IPS = ["127.0.0.1", "localhost"]

# Email backend para desenvolvimento
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Celery task execution: síncrono em dev para simplificar debugging
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
