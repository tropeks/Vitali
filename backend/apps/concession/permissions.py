"""Tier gate for the diagnostic-concession module.

The SaaS owner toggles this per tenant via ``core.FeatureFlag(module_key=
"diagnostic_concession")``. Endpoints in this app gate on ``ConcessionModule``.
"""

from apps.core.permissions import ModuleRequiredPermission

CONCESSION_MODULE_KEY = "diagnostic_concession"


class ConcessionModule(ModuleRequiredPermission):
    """DRF permission: the tenant must have the diagnostic_concession module active."""

    def __init__(self):
        super().__init__(CONCESSION_MODULE_KEY)
