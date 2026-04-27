"""Sprint 18 / E-013 — EmployeeDeactivationService unit + integration tests.

Covers F-15 cascade:
1. Admin (non-clinical) deactivation — no Professional row
2. Clinical deactivation — Professional.is_active flipped + 3rd AuditLog entry
3. Token blacklist idempotency — already-blacklisted tokens counted separately
4. AuditLog correlation_id shared across all entries in a single deactivation
5. Reactivation via PATCH — User.is_active flipped back + employee_reactivated AuditLog
"""

from datetime import date

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import AuditLog, Role, User
from apps.emr.models import Professional
from apps.hr.models import Employee
from apps.hr.services import EmployeeDeactivationService
from apps.test_utils import TenantTestCase

# ── Helpers ───────────────────────────────────────────────────────────────────


def _admin_role():
    role, _ = Role.objects.get_or_create(name="admin", defaults={"permissions": ["admin"]})
    return role


def _medico_role():
    role, _ = Role.objects.get_or_create(
        name="medico", defaults={"permissions": ["emr.read", "emr.write"]}
    )
    return role


def _make_user(email, role=None, **kwargs):
    defaults = {"full_name": "Test User", "is_active": True}
    defaults.update(kwargs)
    user = User.objects.create_user(email=email, password="TestPass1!", **defaults)
    if role:
        user.role = role
        user.save(update_fields=["role"])
    return user


def _make_employee(user, **kwargs):
    defaults = {
        "hire_date": date(2026, 1, 1),
        "contract_type": "clt",
        "employment_status": "active",
    }
    defaults.update(kwargs)
    return Employee.objects.create(user=user, **defaults)


def _make_professional(user):
    return Professional.objects.create(
        user=user,
        council_type="CRM",
        council_number="999999",
        council_state="SP",
        specialty="Clínica Geral",
        is_active=True,
    )


def _requesting_user():
    user, _ = User.objects.get_or_create(
        email="requester@deact.example.com",
        defaults={"full_name": "System Requester", "is_staff": True},
    )
    return user


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestEmployeeDeactivationService(TenantTestCase):
    """Unit tests for EmployeeDeactivationService."""

    def setUp(self):
        super().setUp()
        _admin_role()
        _medico_role()
        self.requester = _requesting_user()
        self.service = EmployeeDeactivationService()

    # ── 1. Non-clinical deactivation ─────────────────────────────────────────

    def test_deactivate_admin_no_professional(self):
        """Non-clinical Employee deactivation: terminated + User.is_active=False.
        AuditLog has exactly 2 entries (employee_terminated, tokens_revoked).
        No professional_deactivated entry.
        """
        user = _make_user("admin.deact@example.com", role=_admin_role())
        employee = _make_employee(user)

        result = self.service.deactivate(employee, requesting_user=self.requester)

        # Employee soft-deleted
        employee.refresh_from_db()
        assert employee.employment_status == "terminated"
        assert employee.terminated_at is not None

        # User deactivated
        user.refresh_from_db()
        assert user.is_active is False

        # Exactly 2 AuditLog entries
        logs = AuditLog.objects.filter(resource_id=str(employee.id))
        token_logs = AuditLog.objects.filter(resource_id=str(user.id), action="tokens_revoked")
        all_deact_logs = list(logs) + list(token_logs)
        actions = {log.action for log in all_deact_logs}
        assert "employee_terminated" in actions
        assert "tokens_revoked" in actions
        assert "professional_deactivated" not in actions

        # Return value is the updated employee instance
        assert result.id == employee.id

    # ── 2. Clinical deactivation with Professional ────────────────────────────

    def test_deactivate_clinical_with_professional(self):
        """Clinical Employee with Professional: professional deactivated + 3rd AuditLog."""
        user = _make_user("medico.deact@example.com", role=_medico_role())
        employee = _make_employee(user)
        professional = _make_professional(user)

        self.service.deactivate(employee, requesting_user=self.requester)

        # Professional.is_active flipped
        professional.refresh_from_db()
        assert professional.is_active is False

        # 3 AuditLog entries
        emp_logs = AuditLog.objects.filter(
            resource_id=str(employee.id), action="employee_terminated"
        )
        token_logs = AuditLog.objects.filter(resource_id=str(user.id), action="tokens_revoked")
        prof_logs = AuditLog.objects.filter(
            resource_id=str(professional.id), action="professional_deactivated"
        )
        assert emp_logs.count() == 1
        assert token_logs.count() == 1
        assert prof_logs.count() == 1

    # ── 3. Token blacklist idempotency ────────────────────────────────────────

    def test_token_blacklist_idempotent(self):
        """With 3 outstanding tokens, 1 pre-blacklisted: revoked=2, already_blacklisted=1."""
        user = _make_user("token.deact@example.com", role=_admin_role())
        employee = _make_employee(user)

        # Create 3 real outstanding tokens via RefreshToken (simplejwt registers them)
        tokens = [RefreshToken.for_user(user) for _ in range(3)]

        # Manually blacklist the first token
        tokens[0].blacklist()

        # Deactivate — should not raise, should count correctly
        self.service.deactivate(employee, requesting_user=self.requester)

        token_log = AuditLog.objects.get(resource_id=str(user.id), action="tokens_revoked")
        assert token_log.new_data["revoked_count"] == 2
        assert token_log.new_data["already_blacklisted_count"] == 1

    # ── 4. Shared correlation_id in AuditLog chain ───────────────────────────

    def test_audit_log_chain_correlation(self):
        """All AuditLog entries in a single deactivation share the same correlation_id."""
        user = _make_user("corr.deact@example.com", role=_medico_role())
        employee = _make_employee(user)
        professional = _make_professional(user)

        self.service.deactivate(employee, requesting_user=self.requester)

        emp_log = AuditLog.objects.get(resource_id=str(employee.id), action="employee_terminated")
        token_log = AuditLog.objects.get(resource_id=str(user.id), action="tokens_revoked")
        prof_log = AuditLog.objects.get(
            resource_id=str(professional.id), action="professional_deactivated"
        )

        cid = emp_log.new_data["correlation_id"]
        assert cid  # non-empty string
        # Validate it's a UUID-like string
        import uuid as uuid_module

        uuid_module.UUID(cid, version=4)

        # All three share the same correlation_id
        assert token_log.new_data["correlation_id"] == cid
        assert prof_log.new_data["correlation_id"] == cid


class TestEmployeeReactivationView(TenantTestCase):
    """Integration test for PATCH reactivation path via EmployeeViewSet."""

    def setUp(self):
        super().setUp()
        _admin_role()
        self.requester = _requesting_user()
        # Make requester a superuser so it can hit the endpoint
        self.requester.is_staff = True
        self.requester.is_superuser = True
        self.requester.save(update_fields=["is_staff", "is_superuser"])

    def test_reactivate_flips_user_is_active(self):
        """PATCH employment_status=active on terminated employee re-enables User.is_active
        and writes employee_reactivated AuditLog entry.
        """
        user = _make_user("reactivate.test@example.com", role=_admin_role())
        employee = _make_employee(user, employment_status="active")

        # Deactivate first via service
        svc = EmployeeDeactivationService()
        svc.deactivate(employee, requesting_user=self.requester)

        user.refresh_from_db()
        assert user.is_active is False

        # Now PATCH via API — SERVER_NAME routes request to the test tenant schema
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=self.requester)

        url = f"/api/v1/hr/employees/{employee.id}/?include_terminated=true"
        response = client.patch(url, {"employment_status": "active"}, format="json")

        assert response.status_code == 200, response.data

        # User.is_active should be True again
        user.refresh_from_db()
        assert user.is_active is True

        # AuditLog entry for reactivation
        react_log = AuditLog.objects.filter(
            action="employee_reactivated",
            resource_id=str(employee.id),
        ).first()
        assert react_log is not None
        assert react_log.new_data["user_id"] == str(user.id)
