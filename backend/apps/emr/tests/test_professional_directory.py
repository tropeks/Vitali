"""RBAC, search and pagination contract for the professional directory."""

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Professional
from apps.test_utils import TenantTestCase


class ProfessionalDirectoryTests(TenantTestCase):
    def setUp(self):
        User = get_user_model()
        self.reception_role = Role.objects.create(
            name="professional_directory_reception",
            permissions=DEFAULT_ROLES["recepcionista"],
        )
        self.receptionist = User.objects.create_user(
            email="reception.directory@test.com",
            password="TestPass123!",
            full_name="Recepcao Directory",
            role=self.reception_role,
        )
        self.professionals = []
        for index, (name, specialty) in enumerate(
            [("Dra. Ana Lima", "Cardiologia"), ("Dr. Bruno Reis", "Ortopedia")], start=1
        ):
            user = User.objects.create_user(
                email=f"professional{index}@test.com",
                password="TestPass123!",
                full_name=name,
            )
            self.professionals.append(
                Professional.objects.create(
                    user=user,
                    council_type="CRM",
                    council_number=f"1000{index}",
                    council_state="SP",
                    specialty=specialty,
                )
            )

    def client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        return client

    def test_receptionist_can_list_paginated_directory(self):
        response = self.client_for(self.receptionist).get("/api/v1/professionals/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_receptionist_can_search_directory(self):
        response = self.client_for(self.receptionist).get(
            "/api/v1/professionals/", {"search": "Cardiologia"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["user_name"], "Dra. Ana Lima")

    def test_directory_honors_bounded_page_size(self):
        response = self.client_for(self.receptionist).get(
            "/api/v1/professionals/", {"page_size": 1}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertIsNotNone(response.json()["next"])

    def test_receptionist_cannot_modify_directory(self):
        response = self.client_for(self.receptionist).post("/api/v1/professionals/", {})

        self.assertEqual(response.status_code, 403)

    def test_tenant_admin_can_modify_directory(self):
        User = get_user_model()
        admin_role = Role.objects.create(
            name="professional_directory_admin",
            permissions=DEFAULT_ROLES["admin"],
        )
        admin = User.objects.create_user(
            email="admin.directory@test.com",
            password="TestPass123!",
            full_name="Tenant Admin",
            role=admin_role,
        )
        response = self.client_for(admin).patch(
            f"/api/v1/professionals/{self.professionals[0].id}/",
            {"specialty": "Clinica Medica"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.professionals[0].refresh_from_db()
        self.assertEqual(self.professionals[0].specialty, "Clinica Medica")
