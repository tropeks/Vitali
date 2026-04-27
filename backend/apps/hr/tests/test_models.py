"""Sprint 18 / E-013 — Employee model unit tests."""

from datetime import date

from apps.core.models import User
from apps.hr.models import Employee
from apps.test_utils import TenantTestCase


class TestEmployeeModel(TenantTestCase):
    def test_employee_str_returns_user_name_and_status(self):
        user = User.objects.create_user(
            email="alice.hr@example.com",
            password="pw",
            full_name="Alice Recursos",
        )
        emp = Employee.objects.create(
            user=user,
            hire_date=date(2026, 1, 15),
            contract_type="clt",
        )
        assert str(emp) == "Alice Recursos (Ativo)"

    def test_employee_default_status_active(self):
        user = User.objects.create_user(
            email="bob.hr@example.com",
            password="pw",
            full_name="Bob HR",
        )
        emp = Employee.objects.create(
            user=user,
            hire_date=date(2026, 2, 1),
            contract_type="pj",
        )
        assert emp.employment_status == "active"
        assert emp.terminated_at is None
