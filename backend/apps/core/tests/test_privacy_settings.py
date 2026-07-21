from unittest.mock import patch

from rest_framework.test import APIClient

from apps.core.models import AIDPAStatus, Role, User
from apps.test_utils import TenantTestCase


class PrivacySettingsViewTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        role = Role.objects.create(name="privacy-admin", permissions=["ai.manage"])
        self.admin = User.objects.create_user(
            email="privacy-admin@test.local",
            password="TestPass123!",
            is_staff=True,
            role=role,
        )
        self.user = User.objects.create_user(
            email="privacy-user@test.local", password="TestPass123!"
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

    def test_non_admin_cannot_update(self):
        self.client.force_authenticate(self.user)
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
