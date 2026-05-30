"""
S-039: ModuleRequiredPermission + IsPlatformAdmin tests.
Run: python manage.py test apps.core.tests.test_permissions
"""

from django.test import override_settings
from rest_framework.test import APIClient, APIRequestFactory

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import (
    HasPermission,
    IsPlatformAdmin,
    ModuleRequiredPermission,
    is_platform_admin,
)
from apps.test_utils import TenantTestCase


class ModulePermissionTestCase(TenantTestCase):
    """ModuleRequiredPermission — flag off → 403, flag on → 200, superuser bypasses."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.role = Role.objects.create(
            name="faturista",
            permissions=["billing.read", "billing.write", "ai.use"],
        )
        self.user = User.objects.create_user(
            email="faturista@test.com",
            password="TestPass123!",
            full_name="Faturista Test",
            role=self.role,
        )
        self.client.force_authenticate(user=self.user)

    def test_module_off_returns_403(self):
        """When billing flag is off, billing endpoints return 403."""
        # Ensure no billing flag
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="billing").delete()

        response = self.client.get("/api/v1/billing/guides/")
        self.assertEqual(response.status_code, 403)

    def test_module_on_returns_200(self):
        """When billing flag is on, billing endpoints are accessible."""
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="billing",
            defaults={"is_enabled": True},
        )
        response = self.client.get("/api/v1/billing/guides/")
        self.assertIn(response.status_code, [200, 404])

    def test_superuser_bypasses_module_gate(self):
        """Superusers bypass ModuleRequiredPermission regardless of FeatureFlag state."""
        super_user = User.objects.create_superuser(
            email="admin@vitali.com",
            password="SuperSecure123!",
            full_name="Platform Admin",
        )
        self.client.force_authenticate(user=super_user)
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="billing").delete()
        response = self.client.get("/api/v1/billing/guides/")
        # Should NOT be 403 even with flag off
        self.assertNotEqual(response.status_code, 403)

    def test_module_required_permission_unit(self):
        """Unit test ModuleRequiredPermission.has_permission() directly."""
        perm = ModuleRequiredPermission("billing")

        # With flag off
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="billing").delete()
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        request.tenant = self.__class__.tenant

        self.assertFalse(perm.has_permission(request, None))

        # With flag on
        FeatureFlag.objects.create(
            tenant=self.__class__.tenant, module_key="billing", is_enabled=True
        )
        self.assertTrue(perm.has_permission(request, None))


class IsPlatformAdminTestCase(TenantTestCase):
    """IsPlatformAdmin — only is_superuser passes."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.role = Role.objects.create(name="admin", permissions=["users.read"])
        self.regular_user = User.objects.create_user(
            email="clinic_admin@test.com",
            password="TestPass123!",
            full_name="Clinic Admin",
            role=self.role,
            is_staff=True,  # staff but NOT superuser
        )
        self.superuser = User.objects.create_superuser(
            email="platform@vitali.com",
            password="PlatformPass123!",
            full_name="Platform Admin",
        )

    def _check(self, user):
        perm = IsPlatformAdmin()
        request = self.factory.get("/")
        request.user = user
        return perm.has_permission(request, None)

    def test_staff_user_rejected(self):
        """is_staff=True alone is NOT enough for platform admin endpoints."""
        self.assertFalse(self._check(self.regular_user))

    def test_superuser_accepted(self):
        """is_superuser=True grants platform admin access."""
        self.assertTrue(self._check(self.superuser))

    def test_anonymous_rejected(self):
        from django.contrib.auth.models import AnonymousUser

        perm = IsPlatformAdmin()
        request = self.factory.get("/")
        request.user = AnonymousUser()
        self.assertFalse(perm.has_permission(request, None))


class PlatformAdminCheckTestCase(TenantTestCase):
    """
    is_platform_admin() — the explicit, auditable replacement for the blanket
    is_superuser bypass.

    A platform operator is a superuser whose email is in the deploy-controlled
    PLATFORM_ADMIN_EMAILS allowlist. A compromised/escalated tenant superuser
    that is NOT on the allowlist must be rejected in production. With no
    allowlist configured the legacy is_superuser bypass survives only under
    DEBUG (local/dev/test convenience) and fails closed in production.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.role = Role.objects.create(name="admin", permissions=["users.read"])
        # A tenant superuser — e.g. a clinic admin escalated by an attacker.
        self.tenant_superuser = User.objects.create_superuser(
            email="escalated@clinic.com",
            password="Escalated123!",
            full_name="Escalated Tenant Superuser",
        )
        # A genuine Vitali platform operator.
        self.platform_operator = User.objects.create_superuser(
            email="ops@vitali.com",
            password="PlatformOps123!",
            full_name="Vitali Platform Operator",
        )
        # A non-superuser that happens to be in the allowlist — must NOT escalate.
        self.regular_user = User.objects.create_user(
            email="ops@vitali.com.regular",
            password="Regular123!",
            full_name="Regular User",
            role=self.role,
        )

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_allowlisted_superuser_is_platform_admin(self):
        self.assertTrue(is_platform_admin(self.platform_operator))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_email_match_is_case_insensitive(self):
        self.platform_operator.email = "OPS@Vitali.com"
        self.assertTrue(is_platform_admin(self.platform_operator))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_tenant_superuser_not_in_allowlist_rejected(self):
        """Compromised tenant superuser not on the allowlist is NOT a platform admin."""
        self.assertFalse(is_platform_admin(self.tenant_superuser))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com.regular"], DEBUG=False)
    def test_non_superuser_in_allowlist_rejected(self):
        """Allowlist membership alone (without is_superuser) must not escalate."""
        self.assertFalse(self.regular_user.is_superuser)
        self.assertFalse(is_platform_admin(self.regular_user))

    @override_settings(PLATFORM_ADMIN_EMAILS=[], DEBUG=False)
    def test_empty_allowlist_fails_closed_in_production(self):
        """No allowlist + production (DEBUG=False) → no platform operators at all."""
        self.assertFalse(is_platform_admin(self.platform_operator))
        self.assertFalse(is_platform_admin(self.tenant_superuser))

    @override_settings(PLATFORM_ADMIN_EMAILS=[], DEBUG=True)
    def test_empty_allowlist_legacy_bypass_under_debug(self):
        """No allowlist + DEBUG → legacy is_superuser bypass preserved for dev/test."""
        self.assertTrue(is_platform_admin(self.platform_operator))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=True)
    def test_anonymous_rejected(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(is_platform_admin(AnonymousUser()))

    # ─── Enforcement through the permission classes ──────────────────────────

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_module_gate_not_bypassed_by_tenant_superuser(self):
        """ModuleRequiredPermission: an escalated tenant superuser does NOT bypass gating."""
        perm = ModuleRequiredPermission("billing")
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="billing"
        ).delete()
        request = self._request(self.tenant_superuser)
        request.tenant = self.__class__.tenant
        self.assertFalse(perm.has_permission(request, None))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_module_gate_bypassed_by_platform_operator(self):
        """ModuleRequiredPermission: a genuine platform operator still bypasses gating."""
        perm = ModuleRequiredPermission("billing")
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="billing"
        ).delete()
        request = self._request(self.platform_operator)
        request.tenant = self.__class__.tenant
        self.assertTrue(perm.has_permission(request, None))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_role_gate_not_bypassed_by_tenant_superuser(self):
        """HasPermission: an escalated tenant superuser falls back to role checks only."""
        perm = HasPermission("emr.read")
        # tenant_superuser has no role granting emr.read.
        self.assertFalse(perm.has_permission(self._request(self.tenant_superuser), None))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_role_gate_bypassed_by_platform_operator(self):
        """HasPermission: a genuine platform operator still bypasses role checks."""
        perm = HasPermission("emr.read")
        self.assertTrue(perm.has_permission(self._request(self.platform_operator), None))

    @override_settings(PLATFORM_ADMIN_EMAILS=["ops@vitali.com"], DEBUG=False)
    def test_is_platform_admin_perm_rejects_tenant_superuser(self):
        """IsPlatformAdmin: platform endpoints reject an escalated tenant superuser."""
        perm = IsPlatformAdmin()
        self.assertFalse(perm.has_permission(self._request(self.tenant_superuser), None))
        self.assertTrue(perm.has_permission(self._request(self.platform_operator), None))


class ModuleGatePharmacyTestCase(TenantTestCase):
    """Pharmacy endpoints gated by pharmacy module flag."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.role = Role.objects.create(
            name="farmaceutico",
            permissions=["pharmacy.read", "pharmacy.stock_manage"],
        )
        self.user = User.objects.create_user(
            email="farm@test.com", password="TestPass123!", full_name="Farm", role=self.role
        )
        self.client.force_authenticate(user=self.user)

    def test_pharmacy_flag_off_returns_403(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="pharmacy").delete()
        response = self.client.get("/api/v1/pharmacy/drugs/")
        self.assertEqual(response.status_code, 403)

    def test_pharmacy_flag_on_returns_200(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        response = self.client.get("/api/v1/pharmacy/drugs/")
        self.assertEqual(response.status_code, 200)
