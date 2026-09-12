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


@register(Tags.security, deploy=True)
def check_deployment_profile_in_production(app_configs, **kwargs):
    """
    Fail the deploy if DEPLOYMENT_PROFILE is not a recognised value in production.

    deploy=True: this check is skipped in normal `manage.py check` (dev/CI) and
    only runs during `manage.py check --deploy`, so the dev suite is unaffected.
    """
    errors = []
    environment = getattr(settings, "ENVIRONMENT", "")
    if environment != "production":
        return errors

    from vitali.settings._security_checks import DEPLOYMENT_PROFILE_CHOICES

    profile = getattr(settings, "DEPLOYMENT_PROFILE", "")
    if profile not in DEPLOYMENT_PROFILE_CHOICES:
        errors.append(
            Error(
                "DEPLOYMENT_PROFILE deve ser 'pool' ou 'dedicated' em produção.",
                hint=(
                    f"O valor atual é {profile!r}. "
                    "Defina DEPLOYMENT_PROFILE=pool (instância SaaS compartilhada, padrão) "
                    "ou DEPLOYMENT_PROFILE=dedicated (instância isolada por clínica — "
                    "Fase 3 Tenant Operator). Air-gap está fora do escopo (cloud only)."
                ),
                id="core.E003",
            )
        )

    return errors


@register(Tags.security, deploy=True)
def check_worker_least_privilege(app_configs, **kwargs):
    """
    Fail the deploy when a Celery worker/beat process uses the web tier's DB DSN.

    The least-privilege boundary is the Postgres credential: workers must connect
    via a dedicated role (CELERY_DATABASE_URL) that holds USAGE/SELECT/INSERT/
    UPDATE/DELETE across all tenant schemas (django-tenants switches search_path)
    but is NOT a superuser and holds no DDL privileges.

    Note: workers STILL require FIELD_ENCRYPTION_KEY — tasks read encrypted EMR
    fields (CPF, etc.) and the crypto key is NOT part of the least-privilege scope.

    deploy=True: skipped in normal `manage.py check` (dev/CI); only runs during
    `manage.py check --deploy`, so the dev suite is unaffected.
    """
    errors = []
    environment = getattr(settings, "ENVIRONMENT", "")
    if environment != "production":
        return errors

    is_worker = getattr(settings, "IS_CELERY_WORKER", False)
    if not is_worker:
        return errors

    from vitali.settings._security_checks import assert_worker_database_separation

    database_url = getattr(settings, "DATABASE_URL", "")
    celery_database_url = getattr(settings, "CELERY_DATABASE_URL", "")
    # Use VITALI_ROLE if available; fall back to "worker" so IS_CELERY_WORKER=True
    # (without VITALI_ROLE override) still triggers the validator correctly.
    role = getattr(settings, "VITALI_ROLE", "worker")
    if role not in ("worker", "beat"):
        role = "worker"  # IS_CELERY_WORKER=True guarantees we are a worker/beat

    try:
        assert_worker_database_separation(role, database_url, celery_database_url)
    except Exception as exc:
        errors.append(
            Error(
                "Workers devem usar um DSN Postgres separado e com menos privilégios (CELERY_DATABASE_URL).",
                hint=(
                    f"{exc} "
                    "Crie um role Postgres dedicado para o worker (sem superuser/DDL), "
                    "com USAGE/SELECT/INSERT/UPDATE/DELETE em todos os schemas de tenant. "
                    "Atenção: workers AINDA precisam de FIELD_ENCRYPTION_KEY — a fronteira "
                    "de least-privilege é a credencial do banco, não a chave de criptografia."
                ),
                id="core.E004",
            )
        )

    return errors


# Catalogs governed by apps.core (SHARED schema) that billing (B6-B9) and clinical
# coding depend on. Keyed by the exact model attribute so the hint can name the
# management command that fixes it — see scripts/catalogs/README.md for the ETL
# that produces each source CSV and apps/core/management/commands/verify_catalogs.py
# for the deploy-time equivalent of this check (run manually; this system-check
# only fires under `manage.py check --deploy`, which is NOT yet wired into CI —
# see docs/research/VITALI_HUMAN_APPLIED_GATES.md, item 2.6).
_ESSENTIAL_CATALOGS = (
    ("core.CID10Code", "import_cid10", "CID-10 (diagnósticos)"),
    ("core.TUSSCode", "import_tuss", "TUSS (faturamento B6-B9)"),
    ("core.CNESEstablishment", "import_cnes", "CNES (estabelecimentos)"),
    ("core.AnvisaProduct", "import_anvisa", "ANVISA medicamentos (faturamento B6-B9)"),
    (
        "core.AnvisaPresentation",
        "import_anvisa_cmed",
        "ANVISA/CMED apresentações (casamento de NF-e)",
    ),
    ("core.SIGTAPProcedure", "import_sigtap", "SIGTAP (faturamento SUS B6-B9)"),
    ("core.CBOCode", "import_cbo", "CBO (ocupações)"),
    ("core.CIDOMorphology", "import_cido", "CID-O (morfologia oncológica)"),
    ("core.UcumUnit", "import_ucum", "UCUM (unidades de medida)"),
)


@register(Tags.security, deploy=True)
def check_catalogs_loaded_in_production(app_configs, **kwargs):
    """
    Fail the deploy if any essential governed catalog (TUSS/ANVISA/SIGTAP/CID-10/
    CNES/CBO/CID-O/UCUM) is empty in production.

    Why this matters: the ETLs in scripts/catalogs/ are run manually against the
    target environment and were, as of this check's introduction, only ever run
    against staging (never production) — see docs/DEPTH_BACKLOG.md P1. An empty
    TUSS/ANVISA/SIGTAP table does not raise any error at billing time: B6-B9
    (dispensed-medication and SUS-procedure billing) simply logs "sem TUSS
    correspondente" at INFO level and skips the line. That is silent, invisible
    revenue loss, not a crash — hence a dedicated deploy gate instead of relying
    on billing code to notice.

    deploy=True: this check is skipped in normal `manage.py check` (dev/CI) and
    only runs during `manage.py check --deploy`, so an empty catalog in a fresh
    dev/test database (the normal, expected state) never blocks anything. It only
    fires when ENVIRONMENT=="production", same guard as core.E002/E003/E004.
    """
    errors = []
    environment = getattr(settings, "ENVIRONMENT", "")
    if environment != "production":
        return errors

    from django.apps import apps as django_apps
    from django.db import DatabaseError

    empty = []
    unverifiable = []
    for label, command, description in _ESSENTIAL_CATALOGS:
        try:
            model = django_apps.get_model(label)
            count = model.objects.count()
        except (DatabaseError, LookupError) as exc:
            # Table not migrated yet, or DB unreachable at check time — do not
            # fail the deploy on our own inability to verify; surface it as its
            # own (separate) problem instead of a false "catalog empty" claim.
            unverifiable.append(f"{description} ({exc.__class__.__name__})")
            continue
        if count == 0:
            empty.append((description, command))

    if empty:
        catalogs_list = "; ".join(f"{desc} → `manage.py {cmd}`" for desc, cmd in empty)
        errors.append(
            Error(
                f"Catálogo(s) essencial(is) vazio(s) em produção: {', '.join(d for d, _ in empty)}.",
                hint=(
                    "Um catálogo vazio não gera erro de faturamento visível — B6-B9 apenas "
                    "deixam de faturar a linha em silêncio (log INFO). Carregue com o "
                    "management command indicado, usando o CSV produzido pelo ETL "
                    "correspondente em scripts/catalogs/README.md: "
                    f"{catalogs_list}. Depois confirme com "
                    "`manage.py verify_catalogs`."
                ),
                id="core.E008",
            )
        )
    if unverifiable:
        errors.append(
            Warning(
                f"Não foi possível verificar {len(unverifiable)} catálogo(s) essencial(is): "
                f"{', '.join(unverifiable)}.",
                hint=(
                    "Provavelmente as migrations do schema public ainda não rodaram, ou o "
                    "banco está inacessível no momento do check. Isto NÃO confirma que o "
                    "catálogo está carregado — rode `manage.py verify_catalogs` depois que "
                    "o banco estiver disponível."
                ),
                id="core.W002",
            )
        )

    return errors
