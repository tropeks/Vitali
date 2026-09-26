"""
Tenant provisioning service (S-132 self-serve signup; ordem 022 made it the
ONLY path).

Originally replaced the per-engineer ``scripts/provision_tenant.sh`` ritual
(removed by ordem 022 — it interpolated the clinic name into a ``manage.py
shell -c`` string) with a single idempotent, transactional code path. Ordem
022 finished the job: this is now the ONE function every way of creating a
tenant calls — ``views_signup.SelfServeSignupView`` (public self-serve
signup), ``views.TenantRegistrationView`` (platform-operator API), and
``manage.py provision_tenant`` (the operator CLI that replaced the shell
script and ``make create-tenant``'s interactive ``shell -c`` blob).

What ``provision_tenant`` does, in order:
  1. Create the :class:`Tenant` (``auto_create_schema=True`` builds the PG schema).
  2. Create (or reuse) the routing :class:`Domain` for ``<slug>.<base-host>``
     (or the caller-supplied ``domain``, verbatim).
  3. Pre-create the current + next month's dedicated ``core_auditlog``
     partition for this tenant (:mod:`apps.core.partitioning`) — so its very
     first audit write never falls back to the shared DEFAULT leaf.
  4. Inside the new schema, seed the default :class:`Role` set and the owner
     :class:`User`, then bind them via :class:`UserTenantMembership` (Model B).
  5. Create the trial :class:`Subscription` (with the requested ``modules``,
     or the self-serve default) linked to the default :class:`Plan`.

Everything after the tenant row is wrapped so a partial failure rolls the WHOLE
thing back — the schema is dropped and no orphaned half-tenant is left behind, so
a retry starts clean rather than colliding with leftovers. That rollback can only
ever reach the tenant THIS call created (see ``created_here`` below) — a
collision against a pre-existing tenant never touches it.
"""

import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.core import partitioning
from apps.core.models import Domain, Plan, Role, Subscription, Tenant, User, UserTenantMembership

logger = logging.getLogger(__name__)


class ProvisioningError(Exception):
    """Raised when tenant provisioning fails after the schema is created."""


class ProvisioningConflict(ProvisioningError):
    """A recoverable, user-caused collision (duplicate CNPJ/email, slug race).

    Carries a machine-readable ``code`` so the caller can map it to a friendly
    409 response instead of a generic 500. Subclasses :class:`ProvisioningError`
    so existing broad ``except ProvisioningError`` handlers still catch it — but
    catch this *first* to branch on the conflict.
    """

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def _classify_integrity_error(exc: Exception) -> str:
    """Map a unique-constraint ``IntegrityError`` to a signup conflict code.

    Postgres puts the violated column/constraint name in the message; we sniff
    it rather than pre-querying so this also covers genuine concurrent races
    (two POSTs with the same CNPJ/email landing between check and INSERT).
    """
    text = str(exc).lower()
    if "cnpj" in text:
        return "CNPJ_TAKEN"
    if "email" in text:
        return "EMAIL_TAKEN"
    if "slug" in text or "schema_name" in text:
        return "SLUG_TAKEN"
    return "CONFLICT"


@dataclass
class ProvisionResult:
    tenant: Tenant
    domain: Domain
    owner: User
    subscription: Subscription | None
    owner_invitation_token: str | None = None


def slugify_company(name: str) -> str:
    """Best-effort slug seed from a company name (ASCII-ish, hyphenated)."""
    value = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    value = value.strip("-")
    return value[:50] or "clinica"


def generate_unique_slug(name: str) -> str:
    """A slug not yet used by any tenant. Appends -2, -3, … on collision."""
    base = slugify_company(name)
    # SlugField regex in the serializer requires 2+ chars and no leading/trailing hyphen.
    if len(base) < 2:
        base = f"{base}-clinica"
    candidate = base
    suffix = 2
    while Tenant.objects.filter(slug=candidate).exists():
        candidate = f"{base[:46]}-{suffix}"
        suffix += 1
    return candidate


def build_domain_url(host: str, slug: str) -> str:
    """Resolve the tenant routing hostname from the request host.

    Mirrors the legacy TenantRegistrationView logic: on localhost we use
    ``<slug>.localhost``; otherwise ``<slug>.<base-domain>``.
    """
    host = (host or "").split(":")[0]
    if not host or "localhost" in host or "127.0.0.1" in host:
        return f"{slug}.localhost"
    base = host.split(".", 1)[-1] if "." in host else host
    return f"{slug}.{base}"


def _default_plan() -> Plan:
    """The plan new self-serve trials are placed on (created on first use)."""
    name = getattr(settings, "SELF_SERVE_DEFAULT_PLAN_NAME", "Starter")
    price = getattr(settings, "SELF_SERVE_DEFAULT_PLAN_PRICE", "299.00")
    plan, _ = Plan.objects.get_or_create(
        name=name,
        defaults={"base_price": price, "is_active": True},
    )
    return plan


def provision_tenant(
    *,
    name: str,
    slug: str,
    cnpj: str = "",
    owner_email: str,
    owner_full_name: str,
    owner_password: str | None = None,
    host: str = "",
    domain: str | None = None,
    modules: list[str] | None = None,
    status: str = Tenant.Status.PENDING,
    trial_days: int | None = None,
    create_subscription: bool = True,
    send_welcome: bool = True,
    created_by: User | None = None,
) -> ProvisionResult:
    """Provision a tenant + owner + trial subscription. See module docstring.

    ``domain``: when given, used verbatim as the routing hostname instead of
    deriving one from ``host`` — the management command passes this
    explicitly rather than deriving it from a request that doesn't exist.

    ``modules``: active module keys for the trial subscription + feature
    flags. ``None`` keeps the existing self-serve default
    (``settings.SELF_SERVE_DEFAULT_MODULES``).
    """
    if User.objects.filter(email=owner_email).exists():
        # Caller should have checked, but guard so we never build a schema we'd
        # only have to roll back (User.email is globally unique in public schema).
        raise ProvisioningConflict("EMAIL_TAKEN", "OWNER_EMAIL_TAKEN")

    domain_url = domain or build_domain_url(host, slug)
    if Domain.objects.filter(domain=domain_url).exists():
        # The tenant we're about to create doesn't exist yet, so ANY existing
        # row here belongs to someone else. Domain.get_or_create used to
        # silently REUSE that other tenant's domain instead of rejecting —
        # checked up front, like the email guard above, so we never build a
        # schema we'd just have to roll back.
        logger.warning(
            "provisioning.conflict slug=%s code=DOMAIN_TAKEN domain=%s", slug, domain_url
        )
        raise ProvisioningConflict("DOMAIN_TAKEN")

    if trial_days is None:
        trial_days = getattr(settings, "SELF_SERVE_TRIAL_DAYS", 14)
    trial_ends_at = timezone.now() + timedelta(days=trial_days)

    tenant = Tenant(
        name=name,
        slug=slug,
        cnpj=cnpj or None,
        status=status,
        trial_ends_at=trial_ends_at,
    )
    try:
        tenant.save()  # triggers schema creation (auto_create_schema=True)
    except IntegrityError as exc:
        # Duplicate CNPJ (unique) or a slug/schema_name race: the INSERT fails
        # *before* the PG schema is built, so there's nothing to roll back — but
        # the raw error must become a friendly 409, not a generic 500. This is
        # the most common real-world re-signup path.
        code = _classify_integrity_error(exc)
        logger.warning("provisioning.conflict slug=%s code=%s err=%s", slug, code, exc)
        raise ProvisioningConflict(code) from exc

    # Only from HERE does a rollback belong to THIS call: the tenant row (and
    # its schema) now exist because WE just created them, so _drop_tenant may
    # touch them. Anything raised above this line has nothing to roll back —
    # in particular, a slug/CNPJ collision against a pre-existing tenant never
    # reaches (and can never drop) that pre-existing tenant.
    created_here = True

    try:
        domain_row, domain_row_created = Domain.objects.get_or_create(
            domain=domain_url,
            defaults={"tenant": tenant, "is_primary": True},
        )
        if not domain_row_created and domain_row.tenant_id != tenant.id:
            # Lost a race: another request claimed this exact hostname between
            # the pre-check above and this INSERT.
            raise ProvisioningConflict("DOMAIN_TAKEN")

        # Order 022: the audit trail must never fall back to the DEFAULT leaf
        # between "clinic created" and the next boot/Beat run of
        # ensure_audit_partitions — pre-create the current + next month's
        # dedicated leaf for THIS tenant now, inside the same rollback guard.
        for month_start in partitioning.month_starts(2):
            partitioning.ensure_tenant_partition(month_start, tenant.schema_name)

        owner = _create_owner(tenant, owner_email, owner_full_name, owner_password)

        subscription = None
        if create_subscription:
            subscription = _create_trial_subscription(tenant, trial_ends_at, modules=modules)

        invitation_token = None
        if send_welcome and owner_password is None:
            from apps.core.services.invitations import issue_password_set_invitation

            _, invitation_token = issue_password_set_invitation(
                owner, tenant=tenant, created_by=created_by
            )
    except ProvisioningConflict as exc:
        logger.warning("provisioning.conflict slug=%s code=%s err=%s", slug, exc.code, exc)
        if created_here:
            _drop_tenant(tenant, slug)
        raise
    except IntegrityError as exc:
        # A concurrent signup won the race between our up-front email pre-check
        # and the owner INSERT (or any other unique collision inside the schema).
        # Roll the half-built schema back and surface a friendly 409, not a 500.
        code = _classify_integrity_error(exc)
        logger.warning("provisioning.conflict slug=%s code=%s err=%s", slug, code, exc)
        if created_here:
            _drop_tenant(tenant, slug)
        raise ProvisioningConflict(code) from exc
    except Exception as exc:  # noqa: BLE001 — re-raised after rollback
        logger.error("provisioning.failed slug=%s err=%s", slug, exc)
        # Drop the half-built schema + tenant row so a retry starts clean.
        if created_here:
            _drop_tenant(tenant, slug)
        raise ProvisioningError(str(exc)) from exc

    logger.info(
        "provisioning.ok slug=%s status=%s owner=%s", tenant.slug, tenant.status, owner_email
    )
    return ProvisionResult(
        tenant=tenant,
        domain=domain_row,
        owner=owner,
        subscription=subscription,
        owner_invitation_token=invitation_token,
    )


def _drop_tenant(tenant: Tenant, slug: str) -> None:
    """Drop the half-built schema + tenant row so a retry starts clean."""
    try:
        tenant.delete(force_drop=True)  # type: ignore[call-arg]
    except Exception as cleanup_exc:  # noqa: BLE001
        logger.error("provisioning.rollback_failed slug=%s err=%s", slug, cleanup_exc)


def _create_owner(tenant, email, full_name, password):
    """Seed default roles + owner user inside the tenant schema (idempotent)."""
    from apps.core.permissions import DEFAULT_ROLES

    with schema_context(tenant.schema_name):
        roles = {}
        for role_name, perms in DEFAULT_ROLES.items():
            role, _ = Role.objects.get_or_create(
                name=role_name,
                defaults={"permissions": perms, "is_system": True},
            )
            roles[role_name] = role

        owner = User(
            email=email,
            full_name=full_name,
            role=roles["admin"],
            is_active=True,
            is_staff=True,
        )
        if password:
            owner.set_password(password)
        else:
            # Passwordless: owner activates via the welcome link. set_unusable_password
            # keeps the account un-loginable until they choose a password.
            owner.set_unusable_password()
            owner.must_change_password = True
        owner.save()

        UserTenantMembership.objects.get_or_create(
            user=owner,
            tenant=tenant,
            defaults={"role": roles["admin"], "is_active": True},
        )
    return owner


def _create_trial_subscription(
    tenant, trial_ends_at, modules: list[str] | None = None
) -> Subscription:
    plan = _default_plan()
    modules = (
        list(modules)
        if modules is not None
        else list(getattr(settings, "SELF_SERVE_DEFAULT_MODULES", ["emr"]))
    )
    today = timezone.now().date()
    subscription = Subscription.objects.create(
        tenant=tenant,
        plan=plan,
        active_modules=modules,
        monthly_price=plan.base_price,
        status=Subscription.Status.ACTIVE,
        current_period_start=today,
        current_period_end=trial_ends_at.date(),
    )
    # Mirror the trial modules into per-tenant FeatureFlags so the frontend
    # module gating (useHasModule) lights up immediately.
    from apps.core.models import FeatureFlag

    for module_key in modules:
        FeatureFlag.objects.get_or_create(
            tenant=tenant, module_key=module_key, defaults={"is_enabled": True}
        )
    return subscription
