"""
RBAC Permission classes for Vitali.
"""

from django.conf import settings
from rest_framework.permissions import BasePermission

from apps.core.utils import tenant_has_feature


def is_platform_admin(user) -> bool:
    """
    True only for genuine Vitali platform operators.

    A platform operator is a Django superuser whose email is listed in the
    explicit, deploy-controlled ``PLATFORM_ADMIN_EMAILS`` allowlist. That
    allowlist lives in environment/deploy configuration — NOT in the
    (tenant-writable) database — so a tenant user who is somehow escalated to
    ``is_superuser`` cannot also grant themselves platform powers: their email
    would still have to appear in the deploy config.

    Backwards-compat fallback: when no allowlist is configured we honour the
    legacy ``is_superuser`` bypass ONLY under DEBUG (local dev / test). In
    production (DEBUG=False) an empty allowlist fails closed — no user is
    treated as a platform operator until ``PLATFORM_ADMIN_EMAILS`` is set.

    ``is_superuser`` remains a precondition so Django admin semantics are
    untouched (admin access keys off ``is_staff`` + model perms, not this
    helper) and a stray allowlist entry alone can never escalate a non-superuser.
    """
    if not (
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    ):
        return False
    allowlist = getattr(settings, "PLATFORM_ADMIN_EMAILS", None) or []
    if allowlist:
        email = (getattr(user, "email", "") or "").strip().lower()
        return email in {entry.strip().lower() for entry in allowlist if entry}
    # No allowlist configured: legacy superuser bypass only outside production.
    return bool(getattr(settings, "DEBUG", False))


class IsPlatformAdmin(BasePermission):
    """
    Grants access only to Vitali platform operators.

    Used for /api/v1/platform/* endpoints — plan management, subscriptions,
    module activation. Clinic owners (even with is_staff) are never superusers,
    and a compromised tenant superuser is rejected unless their email is in the
    deploy-controlled ``PLATFORM_ADMIN_EMAILS`` allowlist (see is_platform_admin).

    Usage:
        permission_classes = [IsAuthenticated, IsPlatformAdmin]
    """

    def has_permission(self, request, view):
        return is_platform_admin(request.user)


class ModuleRequiredPermission(BasePermission):
    """
    Checks that the current tenant has a specific module enabled via FeatureFlag.

    Vitali platform operators (see is_platform_admin) bypass module gating; a
    plain tenant superuser does not. Returns 403 with a clear message if the
    module is inactive.

    Usage:
        _BILLING = ModuleRequiredPermission('billing')
        permission_classes = [IsAuthenticated, _BILLING]

    Note: __call__ returns self so that DRF's get_permissions() works correctly
    when a pre-constructed instance is placed in permission_classes.
    """

    def __init__(self, module_key: str):
        self.module_key = module_key

    def __call__(self):
        return self

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if is_platform_admin(request.user):
            return True
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return False
        return tenant_has_feature(tenant, self.module_key)

    @property
    def message(self):
        return f"Module '{self.module_key}' is not active for this tenant."


class HasPermission(BasePermission):
    """
    Usage:
        permission_classes = [HasPermission('emr.read')]

    Reads the user's Role.permissions list and checks for the required perm.
    Role.permissions is stored as a JSON list: ["emr.read", "emr.write", ...]

    Note: __call__ returns self so that DRF's get_permissions() works correctly
    when a pre-constructed instance is placed in permission_classes.
    """

    def __init__(self, permission_required: str):
        self.permission_required = permission_required

    def __call__(self):
        return self

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if is_platform_admin(request.user):
            return True
        role = getattr(request.user, "role", None)
        if not role:
            return False
        return self.permission_required in role.permissions


# ─── Convenience factory ──────────────────────────────────────────────────────


def require_permission(perm: str):
    """
    Returns a HasPermission instance ready for permission_classes.
    Usage: permission_classes = [IsAuthenticated, require_permission('emr.read')]
    """
    return HasPermission(perm)


# ─── Default role permission sets ─────────────────────────────────────────────

ADMIN_PERMISSIONS = [
    "emr.read",
    "emr.write",
    "emr.sign",
    "emr.delete",
    "patients.read",
    "patients.write",
    "patients.delete",
    "billing.read",
    "billing.write",
    "billing.full",
    "schedule.read",
    "schedule.write",
    "pharmacy.read",
    "pharmacy.dispense",
    "pharmacy.full",
    "pharmacy.catalog_manage",
    "pharmacy.stock_manage",
    "pharmacy.dispense_controlled",
    "users.read",
    "users.write",
    "roles.read",
    "roles.write",
    "reports.read",
    "ai.use",
    "ai.manage",
    "signatures.read",
    "signatures.sign",
    "fhir.read",
    "imaging.read",
    "imaging.write",
    "telemedicine.read",
    "telemedicine.host",
    "pharmacy_ai.read",
    "smart_scheduling.read",
    "triage.read",
    "triage.respond",
    "mobile.admin",
]

CLINICAL_PRESCRIBER_PERMISSIONS = [
    "emr.read",
    "emr.write",
    "emr.sign",
    "patients.read",
    "patients.write",
    "billing.read",
    "schedule.read",
    "schedule.write",
    "pharmacy.read",
    "ai.use",
    "signatures.read",
    "signatures.sign",
    "fhir.read",
    "imaging.read",
    "imaging.write",
    "telemedicine.read",
    "telemedicine.host",
    "smart_scheduling.read",
    "triage.read",
]

NURSING_PERMISSIONS = [
    "emr.read",
    "emr.partial_write",
    "patients.read",
    "schedule.read",
    "pharmacy.dispense",
]

RECEPTION_PERMISSIONS = [
    "patients.limited_read",
    "smart_scheduling.read",
    "schedule.read",
    "schedule.write",
    "billing.read",
    "triage.read",
    "triage.respond",
]

PHARMACY_PERMISSIONS = [
    "emr.read",
    "pharmacy.read",
    "pharmacy.dispense",
    "pharmacy.full",
    "pharmacy.catalog_manage",
    "pharmacy.stock_manage",
    "pharmacy.dispense_controlled",
    "patients.limited_read",
    "pharmacy_ai.read",
]

BILLING_PERMISSIONS = [
    "billing.read",
    "billing.write",
    "billing.full",
    "patients.limited_read",
    "emr.read",
    "ai.use",
]

DEFAULT_ROLES = {
    "admin": ADMIN_PERMISSIONS,
    "medico": CLINICAL_PRESCRIBER_PERMISSIONS,
    "enfermeiro": NURSING_PERMISSIONS,
    "recepcao": RECEPTION_PERMISSIONS,
    "recepcionista": RECEPTION_PERMISSIONS,
    "farmaceutico": PHARMACY_PERMISSIONS,
    "faturista": BILLING_PERMISSIONS,
    "dentista": CLINICAL_PRESCRIBER_PERMISSIONS,
}
