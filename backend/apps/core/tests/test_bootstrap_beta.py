"""Focused regression tests for the beta provisioning command."""

from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django_tenants.utils import schema_context

from apps.core.management.commands.bootstrap_beta import DEFAULT_BETA_MODULES
from apps.core.models import (
    FeatureFlag,
    Plan,
    PlanModule,
    Subscription,
    User,
    UserTenantMembership,
)
from apps.test_utils import TenantTestCase


class BootstrapBetaTests(TenantTestCase):
    password = "BetaAdmin-Strong-2026!"

    def _run(self, **overrides):
        options = {
            "public_domain": "public.bootstrap.test",
            "clinic_slug": self.__class__.tenant.slug,
            "clinic_name": "Clínica Bootstrap",
            "clinic_domain": [self.__class__.domain.domain],
            "admin_email": "beta-admin@bootstrap.test",
            "admin_name": "Admin Beta",
        }
        options.update(overrides)
        with patch.dict("os.environ", {"BOOTSTRAP_ADMIN_PASSWORD": self.password}):
            call_command("bootstrap_beta", **options)

    def test_provisions_clinic_admin_without_platform_privileges(self):
        self._run()

        with schema_context(self.__class__.tenant.schema_name):
            admin = User.objects.get(email="beta-admin@bootstrap.test")
            self.assertTrue(admin.check_password(self.password))
            self.assertTrue(admin.is_staff)
            self.assertFalse(admin.is_superuser)
            self.assertEqual(admin.role.name, "admin")
            membership = UserTenantMembership.objects.get(user=admin, tenant=self.__class__.tenant)
            self.assertTrue(membership.is_active)
            self.assertEqual(membership.role.name, "admin")

    def test_provisions_agreed_mvp_plan_subscription_and_flags(self):
        self._run()

        subscription = Subscription.objects.get(tenant=self.__class__.tenant)
        self.assertEqual(subscription.plan.name, "Beta MVP")
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(subscription.active_modules, list(DEFAULT_BETA_MODULES))
        self.assertEqual(
            set(
                FeatureFlag.objects.filter(
                    tenant=self.__class__.tenant, is_enabled=True
                ).values_list("module_key", flat=True)
            ),
            set(DEFAULT_BETA_MODULES),
        )
        self.assertEqual(
            set(
                PlanModule.objects.filter(plan=subscription.plan, is_included=True).values_list(
                    "module_key", flat=True
                )
            ),
            set(DEFAULT_BETA_MODULES),
        )

    def test_rerun_repairs_legacy_superuser_and_reconciles_modules(self):
        self._run()
        admin = User.objects.get(email="beta-admin@bootstrap.test")
        admin.is_superuser = True
        admin.save(update_fields=["is_superuser"])
        FeatureFlag.objects.create(
            tenant=self.__class__.tenant,
            module_key="dose_safety",
            is_enabled=True,
        )

        self._run(modules=["emr", "billing"], plan_price=Decimal("99.90"))

        admin.refresh_from_db()
        self.assertFalse(admin.is_superuser)
        subscription = Subscription.objects.get(tenant=self.__class__.tenant)
        self.assertEqual(subscription.plan, Plan.objects.get(name="Beta MVP"))
        self.assertEqual(subscription.active_modules, ["emr", "billing"])
        self.assertEqual(str(subscription.monthly_price), "99.90")
        self.assertEqual(
            set(
                PlanModule.objects.filter(plan=subscription.plan, is_included=True).values_list(
                    "module_key", flat=True
                )
            ),
            {"emr", "billing"},
        )
        self.assertFalse(
            FeatureFlag.objects.get(
                tenant=self.__class__.tenant, module_key="dose_safety"
            ).is_enabled
        )
