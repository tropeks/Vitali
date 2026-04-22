"""
S-039: ModuleRequiredPermission + IsPlatformAdmin tests.
Run: python manage.py test apps.core.tests.test_permissions
"""

from rest_framework.test import APIClient, APIRequestFactory

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import IsPlatformAdmin, ModuleRequiredPermission
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
