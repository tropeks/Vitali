"""
RBAC Permission classes for Vitali.
"""
from rest_framework.permissions import BasePermission


class HasPermission(BasePermission):
    """
    Usage:
        permission_classes = [HasPermission('emr.read')]

    Reads the user's Role.permissions list and checks for the required perm.
    Role.permissions is stored as a JSON list: ["emr.read", "emr.write", ...]
    """

    def __init__(self, permission_required: str):
        self.permission_required = permission_required

    # DRF calls has_permission with view as second arg; we need to support
    # both instantiated usage and class-level usage via get_permissions().
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
        "emr.read", "emr.write", "emr.sign", "emr.delete",
        "patients.read", "patients.write", "patients.delete",
        "billing.read", "billing.write", "billing.full",
        "schedule.read", "schedule.write",
        "pharmacy.read", "pharmacy.dispense", "pharmacy.full",
        "pharmacy.catalog_manage", "pharmacy.stock_manage", "pharmacy.dispense_controlled",
        "users.read", "users.write",
        "roles.read", "roles.write",
        "reports.read",
        "ai.use",
    ],
    "medico": [
        "emr.read", "emr.write", "emr.sign",
        "patients.read", "patients.write",
        "billing.read",
        "schedule.read", "schedule.write",
        "pharmacy.read",
        "ai.use",
    ],
    "enfermeiro": [
        "emr.read", "emr.partial_write",
        "patients.read",
        "schedule.read",
        "pharmacy.dispense",
    ],
    "recepcionista": [
        "patients.limited_read",
        "schedule.read", "schedule.write",
        "billing.read",
    ],
    "farmaceutico": [
        "emr.read",
        "pharmacy.read", "pharmacy.dispense", "pharmacy.full",
        "pharmacy.catalog_manage", "pharmacy.stock_manage", "pharmacy.dispense_controlled",
        "patients.limited_read",
    ],
    "faturista": [
        "billing.read", "billing.write", "billing.full",
        "patients.limited_read",
        "emr.read",
    ],
}
