"""
Regression tests for HR RBAC (A01): HRAccessPermission must authorize off a
non-forgeable admin capability (permissions list / is_system admin role) or an
explicit ``hr.manage`` permission — NEVER the user-settable ``role.name``.

Locks in:
- a clinician role gets 403 on list/retrieve/update/destroy of /hr/employees/
- a canonical / is_system admin STILL has HR access (guards the commit-7e921c3
  under-grant from regressing)
- a user whose role is merely NAMED "admin" (non-system, no admin perm) is
  denied — the forged-role escalation vector.
"""

from datetime import date

from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.hr.models import Employee
from apps.test_utils import TenantTestCase


class HRAccessControlTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.admin_role = Role.objects.create(name="admin", permissions=["admin"], is_system=True)
        self.clinician_role = Role.objects.create(
            name="medico", permissions=["emr.read", "emr.write"]
        )

        self.admin = User.objects.create_user(
            email="hr-admin@clinic.test",
            password="TestPass123!",
            full_name="HR Admin",
            role=self.admin_role,
        )
        self.clinician = User.objects.create_user(
            email="hr-doc@clinic.test",
            password="TestPass123!",
            full_name="Dr NonHR",
            role=self.clinician_role,
        )
        employee_user = User.objects.create_user(
            email="employee@clinic.test", password="TestPass123!", full_name="Worker"
        )
        self.employee = Employee.objects.create(
            user=employee_user,
            hire_date=date(2026, 1, 1),
            contract_type="clt",
            employment_status="active",
        )

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    # ─── Clinician is denied every action ────────────────────────────────────

    def test_clinician_denied_list(self):
        self.client.force_authenticate(user=self.clinician)
        self.assertEqual(self.client.get("/api/v1/hr/employees/").status_code, 403)

    def test_clinician_denied_retrieve(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.get(f"/api/v1/hr/employees/{self.employee.id}/")
        self.assertEqual(resp.status_code, 403)

    def test_clinician_denied_update(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.patch(
            f"/api/v1/hr/employees/{self.employee.id}/",
            {"employment_status": "terminated"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_clinician_denied_destroy(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.delete(f"/api/v1/hr/employees/{self.employee.id}/")
        self.assertEqual(resp.status_code, 403)

    # ─── Admin retains access (no under-grant regression) ────────────────────

    def test_canonical_admin_can_list(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get("/api/v1/hr/employees/").status_code, 200)

    def test_legacy_system_admin_without_literal_perm_can_list(self):
        legacy_role = Role.objects.create(name="admin", permissions=[], is_system=True)
        legacy_admin = User.objects.create_user(
            email="legacy-hr-admin@clinic.test",
            password="TestPass123!",
            full_name="Legacy HR Admin",
            role=legacy_role,
        )
        self.client.force_authenticate(user=legacy_admin)
        self.assertEqual(self.client.get("/api/v1/hr/employees/").status_code, 200)

    def test_forged_admin_name_is_denied(self):
        """A non-system role merely named 'admin' must NOT unlock HR."""
        forged_role = Role.objects.create(name="admin", permissions=["emr.read"], is_system=False)
        forged_user = User.objects.create_user(
            email="forged@clinic.test",
            password="TestPass123!",
            full_name="Forged Admin",
            role=forged_role,
        )
        self.client.force_authenticate(user=forged_user)
        self.assertEqual(self.client.get("/api/v1/hr/employees/").status_code, 403)

    def test_hr_manage_delegate_can_list(self):
        """Explicitly delegated HR users (hr.manage) keep access."""
        hr_role = Role.objects.create(name="rh", permissions=["hr.manage"])
        hr_user = User.objects.create_user(
            email="rh@clinic.test",
            password="TestPass123!",
            full_name="RH Ops",
            role=hr_role,
        )
        self.client.force_authenticate(user=hr_user)
        self.assertEqual(self.client.get("/api/v1/hr/employees/").status_code, 200)
