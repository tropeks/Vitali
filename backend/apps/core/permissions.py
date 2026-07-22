"""
RBAC Permission classes for Vitali.
"""

from rest_framework.permissions import BasePermission

from apps.core.utils import tenant_has_feature


def is_platform_admin(user) -> bool:
    """
    True for Vitali platform operators — i.e. Django superusers.

    POLICY (operational, enforced outside the code): ``is_superuser`` is reserved
    for genuine Vitali platform staff. Tenant users — including clinic
    owners/admins — authorize exclusively via roles/permissions and must NEVER be
    created with ``is_superuser=True``. Under that policy, keying platform-admin
    powers off ``is_superuser`` is safe and keeps Django-admin semantics intact.

    The previous blanket bypass was scattered inline across permission classes;
    routing every check through this single helper makes the rule auditable and
    gives one place to harden later (e.g. a deploy-controlled allowlist or a
    dedicated flag) if defense-in-depth against a compromised superuser is needed.
    """
    return bool(
        user and getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False)
    )


class IsPlatformAdmin(BasePermission):
    """
    Grants access only to Vitali platform operators.

    Used for /api/v1/platform/* endpoints — plan management, subscriptions,
    module activation. Access is granted to Django superusers (Vitali platform
    operators); clinic owners authorize via roles and must never be superusers
    (see is_platform_admin for the policy).

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
        # Effective (per-tenant) role under Model B; falls back to the global role
        # when membership roles are not in effect. See User.effective_role.
        role = request.user.effective_role()
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
    "pharmacy.warehouse_manage",
    "pharmacy.inventory_count",
    "pharmacy.inventory_approve",
    "pharmacy.transfer_manage",
    "pharmacy.transfer_accept",
    "pharmacy.recall_manage",
    "pharmacy.quarantine_manage",
    "pharmacy.dispense_controlled",
    "users.read",
    "users.write",
    "roles.read",
    "roles.write",
    "reports.read",
    "privacy.read",
    "privacy.manage",
    "workflow.read",
    "workflow.request",
    "workflow.approve",
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
    "organization.read",
    "organization.write",
    "organization.delete",
    "mpi.read",
    "mpi.write",
    "mpi.review",
    "integrations.operations.read",
    "integrations.replay",
    "emar.read",
    "emar.administer",
    "sae.read",
    "sae.write",
    "pharmacy.clinical_validate",
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
    "emar.read",
    "sae.read",
]

NURSING_PERMISSIONS = [
    "emr.read",
    "emr.partial_write",
    "patients.read",
    "schedule.read",
    "pharmacy.dispense",
    "emar.read",
    "emar.administer",
    "sae.read",
    "sae.write",
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
    "pharmacy.warehouse_manage",
    "pharmacy.inventory_count",
    "pharmacy.inventory_approve",
    "pharmacy.transfer_manage",
    "pharmacy.transfer_accept",
    "pharmacy.recall_manage",
    "pharmacy.quarantine_manage",
    "pharmacy.dispense_controlled",
    "patients.limited_read",
    "pharmacy_ai.read",
    "pharmacy.clinical_validate",
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
