"""Tier gate + RBAC for the diagnostic-concession module.

The SaaS owner toggles the tier per tenant via ``core.FeatureFlag(module_key=
"diagnostic_concession")``. Endpoints in this app gate on ``ConcessionModule``.

On top of the tier gate, ``HasConcessionAccess`` enforces role-based access:
concession is administrative (assets/contracts/P&L), NOT clinical, so a clinical
role such as ``enfermeiro`` must NOT reach it just because the module is active.
Reads require ``concession.read``; writes require ``concession.manage`` — both
carried only by the admin role (see ``ADMIN_PERMISSIONS``).
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.permissions import (
    ModuleRequiredPermission,
    is_platform_admin,
    role_has_admin_capability,
)

CONCESSION_MODULE_KEY = "diagnostic_concession"

CONCESSION_READ = "concession.read"
CONCESSION_MANAGE = "concession.manage"


class ConcessionModule(ModuleRequiredPermission):
    """DRF permission: the tenant must have the diagnostic_concession module active."""

    def __init__(self):
        super().__init__(CONCESSION_MODULE_KEY)


class HasConcessionAccess(BasePermission):
    """RBAC gate for the (administrative) concession module.

    Read/write split by HTTP method:

    - safe methods (GET/HEAD/OPTIONS) require ``concession.read``;
    - write methods (POST/PUT/PATCH/DELETE) require ``concession.manage``.

    Vitali platform operators (see ``is_platform_admin``) and the canonical
    tenant-admin role (see ``role_has_admin_capability``) always pass — the admin
    carries both permissions in ``ADMIN_PERMISSIONS``. A clinical role such as
    ``enfermeiro`` carries neither and is therefore denied (403).

    Note: ``__call__`` returns self so DRF's ``get_permissions()`` works when a
    pre-constructed instance is placed in ``permission_classes`` (mirrors the
    other concession permissions).
    """

    def __call__(self):
        return self

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if is_platform_admin(request.user):
            return True
        role = request.user.effective_role()
        if not role:
            return False
        # The canonical tenant-admin role always passes (keyed off the
        # non-forgeable admin capability, not the user-settable role.name).
        if role_has_admin_capability(role):
            return True
        required = CONCESSION_READ if request.method in SAFE_METHODS else CONCESSION_MANAGE
        return required in (role.permissions or [])
