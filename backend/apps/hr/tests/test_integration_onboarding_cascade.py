"""F-01 (E-013) — full employee-onboarding cascade integration test (issue #120).

Drives the complete onboarding cascade end-to-end through the public API surface,
asserting every acceptance criterion of F-01 in a single flow:

  1. Creating an Employee fires the invite email (auth_mode="invite").
  2. The cascade creates User + Employee + Professional (+ ScheduleConfig) when
     council data is provided, all tied together by one correlation_id (2A).
  3. Roles are assigned per cargo: the new User carries the role passed in.
  4. The invited user accepts the invite (sets a password) using the token from
     the emailed link and can then LOG IN, receiving a JWT whose role matches.

This is the integration counterpart to the unit tests in
test_services_onboarding.py and the thinner per-mode API tests in
test_api_onboarding.py — here the whole chain (HTTP create → invite email →
set-password → login) runs against the real URL routes.
"""

import re
from unittest.mock import patch

from django.core.management import call_command
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User, UserInvitation
from apps.emr.models import Professional, ScheduleConfig
from apps.hr.models import Employee
from apps.test_utils import TenantTestCase


class EmployeeOnboardingCascadeIntegrationTests(TenantTestCase):
    """End-to-end cascade: HTTP create → invite email → set-password → login."""

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
        self.admin = User.objects.create_user(
            email="admin.cascade@test.com",
            password="AdminPass1!",
            full_name="Cascade Admin",
            role=admin_role,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_authenticate(user=self.admin)

    @staticmethod
    def _token_from_invite_email(mock_send) -> str:
        """Extract the set-password JWT from the captured invitation link.

        ``EmailService.send_user_invitation(user, link)`` is called positionally
        by ``_create_invitation_for_user``; the link is
        ``<FRONTEND_URL>/auth/set-password/<token>``.
        """
        assert mock_send.call_count == 1, mock_send.call_args_list
        args, kwargs = mock_send.call_args
        link = kwargs["link"] if "link" in kwargs else args[1]
        match = re.search(r"/set-password/([^/?#]+)", link)
        assert match, f"no set-password token in invite link: {link}"
        return match.group(1)

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_full_cascade_invite_clinical_then_login(self, mock_send):
        # ── 1. Admin onboards a clinical employee in invite mode ──────────────
        resp = self.client.post(
            "/api/v1/hr/employees/",
            {
                "full_name": "Dra. Carla Cascade",
                "email": "carla.cascade@test.com",
                "cpf": "33333333333",
                "role": "medico",
                "hire_date": "2026-02-01",
                "contract_type": "clt",
                "employment_status": "active",
                "council_type": "CRM",
                "council_number": "778899",
                "council_state": "SP",
                "specialty": "Cardiologia",
                "auth_mode": "invite",
                "setup_whatsapp": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        body = resp.json()
        correlation_id = body["correlation_id"]

        # ── 2. Cascade rows exist (User + Employee + Professional + schedule) ─
        user = User.objects.get(email="carla.cascade@test.com")
        self.assertTrue(Employee.objects.filter(user=user).exists())
        # Role assigned per cargo
        self.assertIsNotNone(user.role)
        self.assertEqual(user.role.name, "medico")
        # Invite mode never sets a usable password / change flag
        self.assertFalse(user.must_change_password)

        # Council data provided → Professional + default ScheduleConfig
        professional = Professional.objects.get(user=user)
        self.assertEqual(professional.council_type, "CRM")
        self.assertEqual(professional.council_number, "778899")
        self.assertEqual(professional.council_state, "SP")
        self.assertTrue(ScheduleConfig.objects.filter(professional=professional).exists())

        # ── 3. Invite email fired + UserInvitation row created ────────────────
        mock_send.assert_called_once()
        self.assertTrue(UserInvitation.objects.filter(user=user, consumed_at__isnull=True).exists())

        # AuditLog chain shares the correlation_id (decision 2A — full tracing)
        chain_actions = set(
            AuditLog.objects.filter(new_data__correlation_id=correlation_id).values_list(
                "action", flat=True
            )
        )
        self.assertLessEqual(
            {
                "employee_created",
                "user_created",
                "professional_created",
                "professional_schedule_created",
                "user_invitation_sent",
            },
            chain_actions,
        )

        # ── 4. Invited user accepts the invite using the emailed token ────────
        token = self._token_from_invite_email(mock_send)
        set_pw = self.client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "CarlaStr0ng!"},
            format="json",
        )
        self.assertEqual(set_pw.status_code, 200, set_pw.json())
        # Invitation is now consumed (single-use)
        self.assertTrue(
            UserInvitation.objects.filter(user=user, consumed_at__isnull=False).exists()
        )

        # ── 5. New user can LOG IN; role in the response matches the cargo ────
        login_client = APIClient()
        login_client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        login = login_client.post(
            "/api/v1/auth/login",
            {"email": "carla.cascade@test.com", "password": "CarlaStr0ng!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.json())
        login_body = login.json()
        self.assertIn("access", login_body)
        self.assertIn("refresh", login_body)
        self.assertEqual(login_body["user"]["role_name"], "medico")

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_full_cascade_invite_non_clinical_no_professional(self, mock_send):
        """Non-clinical cargo: cascade still fires the invite + login, no Professional."""
        resp = self.client.post(
            "/api/v1/hr/employees/",
            {
                "full_name": "Recepção Cascade",
                "email": "recepcao.cascade@test.com",
                "cpf": "66666666666",
                "role": "recepcao",
                "hire_date": "2026-02-01",
                "contract_type": "clt",
                "employment_status": "active",
                "auth_mode": "invite",
                "setup_whatsapp": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())

        user = User.objects.get(email="recepcao.cascade@test.com")
        self.assertEqual(user.role.name, "recepcao")
        self.assertFalse(Professional.objects.filter(user=user).exists())

        token = self._token_from_invite_email(mock_send)
        set_pw = self.client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "Recep0Str!"},
            format="json",
        )
        self.assertEqual(set_pw.status_code, 200, set_pw.json())

        login_client = APIClient()
        login_client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        login = login_client.post(
            "/api/v1/auth/login",
            {"email": "recepcao.cascade@test.com", "password": "Recep0Str!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.json())
        self.assertEqual(login.json()["user"]["role_name"], "recepcao")
