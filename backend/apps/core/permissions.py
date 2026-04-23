"""
RBAC Permission classes for Vitali.
"""

from rest_framework.permissions import BasePermission

from apps.core.utils import tenant_has_feature


class IsPlatformAdmin(BasePermission):
    """
    Grants access only to Vitali platform operators (Django superusers).

    Used for /api/v1/platform/* endpoints — plan management, subscriptions,
    module activation. Clinic owners (even with is_staff) are never superusers.

    Usage:
        permission_classes = [IsAuthenticated, IsPlatformAdmin]
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_superuser


class ModuleRequiredPermission(BasePermission):
    """
    Checks that the current tenant has a specific module enabled via FeatureFlag.

    Superusers bypass module gating (platform operators must always have access).
    Returns 403 with a clear message if the module is inactive.

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
        if request.user.is_superuser:
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
        if request.user.is_superuser:
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


# ─── Default role permission sets ────────────────────────────────────────────

DEFAULT_ROLES = {
    "admin": [
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
    ],
    "medico": [
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
    ],
    "enfermeiro": [
        "emr.read",
        "emr.partial_write",
        "patients.read",
        "schedule.read",
        "pharmacy.dispense",
    ],
    "recepcionista": [
        "patients.limited_read",
        "schedule.read",
        "schedule.write",
        "billing.read",
    ],
    "farmaceutico": [
        "emr.read",
        "pharmacy.read",
        "pharmacy.dispense",
        "pharmacy.full",
        "pharmacy.catalog_manage",
        "pharmacy.stock_manage",
        "pharmacy.dispense_controlled",
        "patients.limited_read",
    ],
    "faturista": [
        "billing.read",
        "billing.write",
        "billing.full",
        "patients.limited_read",
        "emr.read",
        "ai.use",
    ],
}
