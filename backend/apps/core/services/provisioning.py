"""
Tenant provisioning service (S-132 self-serve signup).

Replaces the per-engineer ``scripts/provision_tenant.sh`` ritual with a single
idempotent, transactional code path that both the public self-serve signup
endpoint and the platform-admin registration view call.

What ``provision_tenant`` does, in order:
  1. Create the :class:`Tenant` (``auto_create_schema=True`` builds the PG schema).
  2. Create (or reuse) the routing :class:`Domain` for ``<slug>.<base-host>``.
  3. Inside the new schema, seed the default :class:`Role` set and the owner
     :class:`User`, then bind them via :class:`UserTenantMembership` (Model B).
  4. Create the trial :class:`Subscription` linked to the default :class:`Plan`.

Everything after the tenant row is wrapped so a partial failure rolls the WHOLE
thing back — the schema is dropped and no orphaned half-tenant is left behind, so
a retry starts clean rather than colliding with leftovers.
"""

import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.core.models import Domain, Plan, Role, Subscription, Tenant, User, UserTenantMembership

logger = logging.getLogger(__name__)


class ProvisioningError(Exception):
    """Raised when tenant provisioning fails after the schema is created."""


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
    status: str = Tenant.Status.PENDING,
    trial_days: int | None = None,
    create_subscription: bool = True,
    send_welcome: bool = True,
    created_by: User | None = None,
) -> ProvisionResult:
    """Provision a tenant + owner + trial subscription. See module docstring."""
    if User.objects.filter(email=owner_email).exists():
        # Caller should have checked, but guard so we never build a schema we'd
        # only have to roll back (User.email is globally unique in public schema).
        raise ProvisioningError("OWNER_EMAIL_TAKEN")

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
    tenant.save()  # triggers schema creation (auto_create_schema=True)

    try:
        domain_url = build_domain_url(host, tenant.slug)
        domain, _ = Domain.objects.get_or_create(
            domain=domain_url,
            defaults={"tenant": tenant, "is_primary": True},
        )

        owner = _create_owner(tenant, owner_email, owner_full_name, owner_password)

        subscription = None
        if create_subscription:
            subscription = _create_trial_subscription(tenant, trial_ends_at)

        invitation_token = None
        if send_welcome and owner_password is None:
            from apps.core.services.invitations import issue_password_set_invitation

            _, invitation_token = issue_password_set_invitation(
                owner, tenant=tenant, created_by=created_by
            )
    except Exception as exc:  # noqa: BLE001 — re-raised after rollback
        logger.error("provisioning.failed slug=%s err=%s", slug, exc)
        # Drop the half-built schema + tenant row so a retry starts clean.
        try:
            tenant.delete(force_drop=True)  # type: ignore[call-arg]
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.error("provisioning.rollback_failed slug=%s err=%s", slug, cleanup_exc)
        raise ProvisioningError(str(exc)) from exc

    logger.info(
        "provisioning.ok slug=%s status=%s owner=%s", tenant.slug, tenant.status, owner_email
    )
    return ProvisionResult(
        tenant=tenant,
        domain=domain,
        owner=owner,
        subscription=subscription,
        owner_invitation_token=invitation_token,
    )


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


def _create_trial_subscription(tenant, trial_ends_at) -> Subscription:
    plan = _default_plan()
    modules = list(getattr(settings, "SELF_SERVE_DEFAULT_MODULES", ["emr"]))
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
