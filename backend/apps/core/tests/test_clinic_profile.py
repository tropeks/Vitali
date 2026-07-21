"""
Tests for issue #116 — clinic identity endpoint used by the onboarding wizard.

Covers:
  - GET  /settings/clinic/ returns the tenant's current identity
  - PATCH /settings/clinic/ updates razão social, endereço and DPO contact
  - PATCH normalises a blank CNPJ to NULL (avoids unique "" collisions)
  - Non-admin (no users.write) is forbidden
"""

from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.test_utils import TenantTestCase


class ClinicProfileViewTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.admin_role = Role.objects.create(
            name="admin",
            permissions=["emr.read", "users.write"],
            is_system=True,
        )
        self.admin = User.objects.create_user(
            email="admin_clinic@clinic.test",
            full_name="Admin Clinic",
            password="TestPass123!",
            role=self.admin_role,
        )
        self.recep_role = Role.objects.create(
            name="recepcao",
            permissions=["patients.limited_read"],
        )
        self.recep = User.objects.create_user(
            email="recep_clinic@clinic.test",
            full_name="Recep Clinic",
            password="TestPass123!",
            role=self.recep_role,
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def test_get_returns_clinic_identity(self):
        self._auth(self.admin)
        resp = self.client.get("/api/v1/settings/clinic/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for field in ("name", "cnpj", "razao_social", "address", "dpo_name", "dpo_email"):
            self.assertIn(field, data)

    def test_patch_updates_identity_and_dpo(self):
        self._auth(self.admin)
        resp = self.client.patch(
            "/api/v1/settings/clinic/",
            {
                "razao_social": "Clínica Vitali LTDA",
                "cnpj": "12.345.678/0001-90",
                "address": "Av. Paulista, 1000 - São Paulo/SP",
                "dpo_name": "Maria DPO",
                "dpo_email": "dpo@clinica.test",
                "dpo_phone": "+55 11 99999-0000",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["razao_social"], "Clínica Vitali LTDA")
        self.assertEqual(data["dpo_email"], "dpo@clinica.test")

        tenant = self.__class__.tenant
        tenant.refresh_from_db()
        self.assertEqual(tenant.razao_social, "Clínica Vitali LTDA")
        self.assertEqual(tenant.cnpj, "12.345.678/0001-90")
        self.assertEqual(tenant.dpo_name, "Maria DPO")

    def test_patch_blank_cnpj_becomes_null(self):
        self._auth(self.admin)
        resp = self.client.patch(
            "/api/v1/settings/clinic/",
            {"cnpj": "", "razao_social": "Sem CNPJ"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        tenant = self.__class__.tenant
        tenant.refresh_from_db()
        self.assertIsNone(tenant.cnpj)

    def test_non_admin_forbidden(self):
        self._auth(self.recep)
        resp = self.client.patch(
            "/api/v1/settings/clinic/",
            {"razao_social": "Hacker"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
