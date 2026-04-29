"""API regression tests for the HR onboarding flows covered by Playwright E2E."""

from unittest.mock import patch

from django.core.management import call_command
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import Professional
from apps.hr.models import Employee
from apps.test_utils import TenantTestCase


class EmployeeOnboardingAPITests(TenantTestCase):
    def setUp(self):
        super().setUp()
        call_command(
            "create_default_roles",
            schema=self.__class__.tenant.schema_name,
            overwrite=True,
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        admin_role = Role.objects.get(name="admin")
        self.admin, _ = User.objects.get_or_create(
            email="admin.hr-api@test.com",
            defaults={
                "full_name": "HR API Admin",
                "role": admin_role,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        self.admin.full_name = self.admin.full_name or "HR API Admin"
        self.admin.role = admin_role
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.is_active = True
        self.admin.set_password("AdminPass1!")
        self.admin.save(
            update_fields=[
                "full_name",
                "role",
                "is_staff",
                "is_superuser",
                "is_active",
                "password",
            ]
        )
        self.client.force_authenticate(user=self.admin)

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_create_recepcao_employee_with_invite_mode(self, mock_send):
        response = self.client.post(
            "/api/v1/hr/employees/",
            {
                "full_name": "Convidado E2E",
                "email": "convidado.api@test.com",
                "cpf": "22222222222",
                "role": "recepcao",
                "hire_date": "2026-01-01",
                "contract_type": "clt",
                "employment_status": "active",
                "auth_mode": "invite",
                "setup_whatsapp": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertTrue(Employee.objects.filter(user__email="convidado.api@test.com").exists())
        mock_send.assert_called_once()

    def test_create_medico_employee_with_random_password_creates_professional(self):
        response = self.client.post(
            "/api/v1/hr/employees/",
            {
                "full_name": "Dr. E2E",
                "email": "dr.api@test.com",
                "cpf": "11111111111",
                "phone": "+5511999999999",
                "role": "medico",
                "hire_date": "2026-01-01",
                "contract_type": "clt",
                "employment_status": "active",
                "council_type": "CRM",
                "council_number": "123456",
                "council_state": "SP",
                "specialty": "Clínica Médica",
                "auth_mode": "random_password",
                "password": "GeneratedPass123!",
                "setup_whatsapp": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertTrue(Employee.objects.filter(user__email="dr.api@test.com").exists())
        self.assertTrue(Professional.objects.filter(user__email="dr.api@test.com").exists())

    def test_create_dentista_employee_with_seeded_default_role(self):
        response = self.client.post(
            "/api/v1/hr/employees/",
            {
                "full_name": "Dra. Dental",
                "email": "dentista.api@test.com",
                "cpf": "44444444444",
                "role": "dentista",
                "hire_date": "2026-01-01",
                "contract_type": "pj",
                "employment_status": "active",
                "council_type": "CRO",
                "council_number": "654321",
                "council_state": "SP",
                "specialty": "Odontologia",
                "auth_mode": "random_password",
                "password": "GeneratedPass123!",
                "setup_whatsapp": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertTrue(Employee.objects.filter(user__email="dentista.api@test.com").exists())
        self.assertTrue(Professional.objects.filter(user__email="dentista.api@test.com").exists())

    def test_legacy_frontend_employee_enum_aliases_are_normalized(self):
        response = self.client.post(
            "/api/v1/hr/employees/",
            {
                "full_name": "Alias Legado",
                "email": "alias.legado@test.com",
                "cpf": "55555555555",
                "role": "recepcao",
                "hire_date": "2026-01-01",
                "contract_type": "estagiario",
                "employment_status": "on_leave",
                "auth_mode": "typed_password",
                "password": "GeneratedPass123!",
                "setup_whatsapp": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        employee = Employee.objects.get(user__email="alias.legado@test.com")
        self.assertEqual(employee.contract_type, "estagio")
        self.assertEqual(employee.employment_status, "leave")
