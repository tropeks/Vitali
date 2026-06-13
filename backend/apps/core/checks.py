"""
Django system checks — fail the deploy if E2E_MODE is enabled outside a test DB,
or if ENFORCE_TENANT_MEMBERSHIP is disabled in production.
Wired in apps/core/apps.py CoreConfig.ready().
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register()
def check_e2e_mode_only_on_test_db(app_configs, **kwargs):
    errors = []
    e2e_mode = getattr(settings, "E2E_MODE", False)
    if not e2e_mode:
        return errors

    db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
    if not db_name.endswith("_test"):
        errors.append(
            Error(
                "E2E_MODE is enabled but the default DB name does not end with '_test'.",
                hint=(
                    "E2E_MODE exposes test-only endpoints that mint JWTs for any user. "
                    "Set E2E_MODE=False, or rename the database to end with '_test'. "
                    f"Current DB name: {db_name!r}"
                ),
                id="core.E001",
            )
        )

    # Soft warning if SECRET_KEY looks like a production key (entropy heuristic)
    secret_key = getattr(settings, "SECRET_KEY", "")
    if (
        e2e_mode
        and len(secret_key) >= 50
        and not secret_key.startswith(("test-", "dev-", "django-insecure-"))
    ):
        errors.append(
            Warning(
                "E2E_MODE is enabled with a SECRET_KEY that looks production-grade.",
                hint=(
                    "JWT tokens issued by the test endpoint are signed with this SECRET_KEY. "
                    "If E2E_MODE accidentally runs against a system that shares the production "
                    "SECRET_KEY, those tokens would be accepted by production. Use a dedicated "
                    "test SECRET_KEY (prefix with 'test-' or 'dev-')."
                ),
                id="core.W001",
            )
        )

    return errors


@register(Tags.security, deploy=True)
def check_tenant_enforcement_in_production(app_configs, **kwargs):
    """
    Fail the deploy if ENFORCE_TENANT_MEMBERSHIP is False in production.

    deploy=True: this check is skipped in normal `manage.py check` (dev/CI) and
    only runs during `manage.py check --deploy`, so the dev suite is unaffected.
    """
    errors = []
    environment = getattr(settings, "ENVIRONMENT", "")
    if environment != "production":
        return errors

    enforce = getattr(settings, "ENFORCE_TENANT_MEMBERSHIP", False)
    if enforce is not True:
        errors.append(
            Error(
                "ENFORCE_TENANT_MEMBERSHIP deve ser True em produção.",
                hint=(
                    "Rode o management command backfill_tenant_memberships para popular "
                    "a tabela de membros e em seguida ligue ENFORCE_TENANT_MEMBERSHIP=True "
                    "na variável de ambiente do container de produção."
                ),
                id="core.E002",
            )
        )

    return errors
