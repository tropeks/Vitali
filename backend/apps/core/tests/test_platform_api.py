"""
S-040: Platform Admin Subscription API tests.
Run: python manage.py test apps.core.tests.test_platform_api
"""
import datetime
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Plan, PlanModule, Role, Subscription, Tenant, User


class PlatformAPITestCase(TenantTestCase):
    """Platform admin CRUD + activate/deactivate module flow."""

    def setUp(self):
        self.client = APIClient()
        # Platform admin = superuser
        self.admin = User.objects.create_superuser(
            email="platform@vitali.com",
            password="PlatformAdmin123!",
            full_name="Platform Admin",
        )
        self.client.force_authenticate(user=self.admin)

        # Regular staff user — should be rejected
        role = Role.objects.create(name="admin", permissions=["users.read"])
        self.staff_user = User.objects.create_user(
            email="staff@clinic.com",
            password="Staff123!",
            full_name="Staff",
            role=role,
            is_staff=True,
        )

        self.plan = Plan.objects.create(
            name="Clínica Test",
            base_price=500.00,
            is_active=True,
        )
        PlanModule.objects.create(
            plan=self.plan, module_key="emr", price=0, is_included=True
        )
        PlanModule.objects.create(
            plan=self.plan, module_key="billing", price=100, is_included=True
        )

    def test_staff_cannot_access_platform_endpoints(self):
        """is_staff alone must not grant access to platform admin endpoints."""
        self.client.force_authenticate(user=self.staff_user)
        resp = self.client.get("/api/v1/platform/plans/")
        self.assertEqual(resp.status_code, 403)

    def test_list_plans(self):
        resp = self.client.get("/api/v1/platform/plans/")
        self.assertEqual(resp.status_code, 200)
        # The list endpoint returns paginated data: {"count": ..., "results": [...]}
        results = resp.data.get("results", resp.data)
        names = [p["name"] for p in results]
        self.assertIn("Clínica Test", names)

    def test_create_plan(self):
        resp = self.client.post(
            "/api/v1/platform/plans/",
            {"name": "Plus", "base_price": "800.00", "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["name"], "Plus")

    def test_create_subscription_enables_flags(self):
        """Creating a Subscription via signal auto-enables FeatureFlag rows."""
        tenant = self.__class__.tenant
        # Clean slate
        FeatureFlag.objects.filter(tenant=tenant).delete()

        sub = Subscription.objects.create(
            tenant=tenant,
            plan=self.plan,
            active_modules=["emr", "billing"],
            monthly_price=600,
            status="active",
            current_period_start=datetime.date.today(),
            current_period_end=datetime.date.today().replace(year=datetime.date.today().year + 1),
        )

        # Signal should have created FeatureFlags
        self.assertTrue(
            FeatureFlag.objects.filter(tenant=tenant, module_key="emr", is_enabled=True).exists()
        )
        self.assertTrue(
            FeatureFlag.objects.filter(tenant=tenant, module_key="billing", is_enabled=True).exists()
        )

    def test_activate_module(self):
        """POST activate-module creates/enables FeatureFlag in public schema."""
        tenant = self.__class__.tenant
        sub = Subscription.objects.create(
            tenant=tenant,
            plan=self.plan,
            active_modules=["emr"],
            monthly_price=500,
            status="active",
            current_period_start=datetime.date.today(),
            current_period_end=datetime.date.today().replace(year=datetime.date.today().year + 1),
        )
        FeatureFlag.objects.filter(tenant=tenant, module_key="pharmacy").delete()

        resp = self.client.post(
            f"/api/v1/platform/subscriptions/{sub.id}/activate-module/",
            {"module_key": "pharmacy"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            FeatureFlag.objects.filter(
                tenant=tenant, module_key="pharmacy", is_enabled=True
            ).exists()
        )

    def test_deactivate_module(self):
        """POST deactivate-module disables FeatureFlag."""
        tenant = self.__class__.tenant
        sub = Subscription.objects.create(
            tenant=tenant,
            plan=self.plan,
            active_modules=["emr", "billing"],
            monthly_price=600,
            status="active",
            current_period_start=datetime.date.today(),
            current_period_end=datetime.date.today().replace(year=datetime.date.today().year + 1),
        )
        FeatureFlag.objects.update_or_create(
            tenant=tenant, module_key="billing",
            defaults={"is_enabled": True},
        )

        resp = self.client.post(
            f"/api/v1/platform/subscriptions/{sub.id}/deactivate-module/",
            {"module_key": "billing"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        flag = FeatureFlag.objects.get(tenant=tenant, module_key="billing")
        self.assertFalse(flag.is_enabled)

    def test_new_tenant_signal_creates_emr_flag(self):
        """post_save on Tenant auto-creates emr FeatureFlag.

        Tests the signal handler directly rather than creating a new schema — creating
        a new Tenant inside TenantTestCase's wrapping transaction causes
        "cannot ALTER TABLE because it has pending trigger events" in PostgreSQL.
        """
        from apps.core.signals import create_tenant_defaults_on_new_tenant

        tenant = self.__class__.tenant
        FeatureFlag.objects.filter(tenant=tenant, module_key="emr").delete()

        create_tenant_defaults_on_new_tenant(sender=Tenant, instance=tenant, created=True)

        self.assertTrue(
            FeatureFlag.objects.filter(
                tenant=tenant, module_key="emr", is_enabled=True
            ).exists()
        )
