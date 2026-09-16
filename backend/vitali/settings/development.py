"""
Vitali — Development Settings
"""

from typing import cast

import environ

from .base import *  # noqa: F401, F403

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

# E2E/CI only: relax the per-IP login throttle. The Playwright suite performs
# a real UI login in nearly every spec from a single runner IP; at the
# production rate (5/min) any failing spec's retry compresses the run and the
# later specs' logins get 429'd (cascade seen in master run 29796568439).
# Gated on E2E_MODE so plain local development keeps production-like limits.
if E2E_MODE:  # noqa: F405 — defined in base.py from the E2E_MODE env var
    # cast: mypy sees REST_FRAMEWORK as dict[str, object] through the star import
    cast(dict[str, str], REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])["login"] = "100/min"  # noqa: F405


# ── Cadeia ICP-Brasil: dev e CI assinam sem âncoras (ordem 015) ──────────────
#
# A partir da ordem 015, trust store vazio + ICP_BRASIL_ENFORCE_CHAIN=True faz o
# signer RECUSAR a assinatura, em vez de gravá-la como não-ICP em silêncio — é o
# que staging e produção precisam, porque assinatura sem valor legal gravada com
# 201 é o pior "verde que não significa verde" deste sistema.
#
# Dev e CI não têm (nem devem ter) o bundle do ITI: aqui o regime antigo continua,
# agora por ESCOLHA EXPLÍCITA e não por herança do default. Sem esta linha, toda
# a suíte de assinatura passaria a falhar por falta de âncoras — falha que não
# diria nada sobre o código sob teste.
ICP_BRASIL_ENFORCE_CHAIN = env.bool("ICP_BRASIL_ENFORCE_CHAIN", default=False)  # noqa: F405
