from unittest.mock import patch

from django.test import override_settings
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIClient

from apps.core.models import AIDPAStatus, Domain, Role, Tenant, User, UserTenantMembership
from apps.test_utils import TenantTestCase


@override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
class PrivacySettingsViewTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.read_role = Role.objects.create(name="privacy-reader", permissions=["privacy.read"])
        self.manage_role = Role.objects.create(
            name="privacy-manager", permissions=["privacy.read", "privacy.manage"]
        )
        self.no_privacy_role = Role.objects.create(
            name="privacy-unrelated", permissions=["ai.manage"]
        )
        self.admin = User.objects.create_user(
            email="privacy-admin@test.local",
            password="TestPass123!",
            is_staff=True,
            role=self.no_privacy_role,
        )
        self.user = User.objects.create_user(
            email="privacy-user@test.local",
            password="TestPass123!",
            role=self.no_privacy_role,
        )
        UserTenantMembership.objects.create(
            user=self.admin,
            tenant=self.__class__.tenant,
            role=self.manage_role,
        )
        UserTenantMembership.objects.create(
            user=self.user,
            tenant=self.__class__.tenant,
            role=self.read_role,
        )

    def test_get_is_authenticated_and_scoped_to_request_tenant(self):
        self.__class__.tenant.dpo_name = "DPO da clínica"
        self.__class__.tenant.dpo_email = "dpo@clinic.test"
        self.__class__.tenant.save(update_fields=["dpo_name", "dpo_email"])
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/v1/tenant/privacy-settings/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "dpo_name": "DPO da clínica",
                "dpo_email": "dpo@clinic.test",
                "dpa_signed": False,
            },
        )

    def test_unauthenticated_request_is_rejected(self):
        self.assertEqual(self.client.get("/api/v1/tenant/privacy-settings/").status_code, 401)

    def test_user_without_privacy_read_cannot_read(self):
        unrelated_user = User.objects.create_user(
            email="privacy-none@test.local",
            password="TestPass123!",
            role=self.manage_role,
        )
        UserTenantMembership.objects.create(
            user=unrelated_user,
            tenant=self.__class__.tenant,
            role=self.no_privacy_role,
        )
        self.client.force_authenticate(unrelated_user)

        response = self.client.get("/api/v1/tenant/privacy-settings/")

        self.assertEqual(response.status_code, 403)

    @patch("apps.core.tasks.send_dpa_signed_admin_email.delay")
    def test_admin_updates_dpo_and_signs_dpa(self, _email_delay):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/tenant/privacy-settings/",
            {"dpo_name": "Nova DPO", "dpo_email": "nova@clinic.test", "dpa_signed": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.__class__.tenant.refresh_from_db()
        self.assertEqual(self.__class__.tenant.dpo_name, "Nova DPO")
        self.assertTrue(AIDPAStatus.objects.get(tenant=self.__class__.tenant).is_signed)

    def test_privacy_reader_cannot_update(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/tenant/privacy-settings/",
            {"dpo_name": "Intruso", "dpo_email": "x@test.local", "dpa_signed": False},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_is_staff_without_privacy_manage_cannot_update(self):
        staff_user = User.objects.create_user(
            email="privacy-staff-only@test.local",
            password="TestPass123!",
            is_staff=True,
            role=self.no_privacy_role,
        )
        UserTenantMembership.objects.create(
            user=staff_user,
            tenant=self.__class__.tenant,
            role=self.read_role,
        )
        self.client.force_authenticate(staff_user)

        response = self.client.post(
            "/api/v1/tenant/privacy-settings/",
            {"dpo_name": "Intruso", "dpo_email": "x@test.local", "dpa_signed": False},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_signed_dpa_cannot_be_removed_or_partially_update_dpo(self):
        AIDPAStatus.objects.create(tenant=self.__class__.tenant, dpa_signed_date="2026-07-21")
        self.__class__.tenant.dpo_name = "DPO original"
        self.__class__.tenant.save(update_fields=["dpo_name"])
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/tenant/privacy-settings/",
            {"dpo_name": "Não salvar", "dpo_email": "x@test.local", "dpa_signed": False},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.__class__.tenant.refresh_from_db()
        self.assertEqual(self.__class__.tenant.dpo_name, "DPO original")


@override_settings(ENFORCE_TENANT_MEMBERSHIP=True)
class PrivacySettingsMultiTenantAuthorizationTests(TenantTestCase):
    def setUp(self):
        with schema_context(get_public_schema_name()):
            self.tenant_b = Tenant.objects.create(name="Privacy Clinic B", slug="privacy-b")
            self.domain_b = Domain.objects.create(
                tenant=self.tenant_b,
                domain="privacy-b.testserver",
                is_primary=True,
            )

        manager = Role.objects.create(
            name="privacy-cross-tenant-manager",
            permissions=["privacy.read", "privacy.manage"],
        )
        reader = Role.objects.create(
            name="privacy-cross-tenant-reader",
            permissions=["privacy.read"],
        )
        self.user = User.objects.create_user(
            email="privacy-cross-tenant@test.local",
            password="TestPass123!",
            role=manager,
        )
        UserTenantMembership.objects.create(
            user=self.user,
            tenant=self.__class__.tenant,
            role=manager,
        )
        UserTenantMembership.objects.create(
            user=self.user,
            tenant=self.tenant_b,
            role=reader,
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.domain_b.domain
        self.client.force_authenticate(self.user)

    def tearDown(self):
        with schema_context(get_public_schema_name()):
            try:
                self.tenant_b.delete(force_drop=True)
            except Exception:
                self.tenant_b.delete()

    def test_manage_permission_from_tenant_a_does_not_authorize_tenant_b(self):
        response = self.client.post(
            "/api/v1/tenant/privacy-settings/",
            {"dpo_name": "Cross tenant", "dpo_email": "cross@test.local", "dpa_signed": False},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.tenant_b.refresh_from_db()
        self.assertEqual(self.tenant_b.dpo_name, "")
