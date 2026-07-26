"""S2-T2 — LeaveRequest via governance maker-checker."""

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.models import Role, User
from apps.governance.models import ApprovalRequest
from apps.hr.models import Employee, LeaveRequest
from apps.hr.services import LeaveService
from apps.test_utils import TenantTestCase


def _employee(email="leaver@clinic.test", name="Leaver"):
    user = User.objects.create_user(email=email, password="pw", full_name=name)
    return Employee.objects.create(user=user, hire_date=date(2026, 1, 1), contract_type="clt")


class LeaveRequestFlowTests(TenantTestCase):
    def setUp(self):
        maker_role = Role.objects.create(
            name="hr-maker", permissions=["workflow.read", "workflow.request"]
        )
        checker_role = Role.objects.create(
            name="hr-checker",
            permissions=["workflow.read", "workflow.approve", "hr.leave.approve"],
        )
        self.maker = User.objects.create_user(email="hrmaker@test.local", role=maker_role)
        self.checker = User.objects.create_user(email="hrchecker@test.local", role=checker_role)
        self.employee = _employee()

    def _request(self, start=date(2026, 8, 1), end=date(2026, 8, 15), requested_by=None):
        return LeaveService.request_leave(
            employee=self.employee,
            requested_by=requested_by or self.maker,
            leave_type=LeaveRequest.Type.VACATION,
            start_date=start,
            end_date=end,
            reason="Férias anuais",
        )

    def test_request_creates_pending_leave_and_approval(self):
        leave = self._request()
        assert leave.status == LeaveRequest.Status.PENDING
        assert leave.approval is not None
        assert leave.approval.status == ApprovalRequest.Status.PENDING
        assert leave.approval.reference_type == "leave_request"

    def test_checker_approves_leave_active_for_period(self):
        leave = self._request()
        LeaveService.decide(leave=leave, actor=self.checker, approve=True)
        leave.refresh_from_db()
        assert leave.status == LeaveRequest.Status.APPROVED
        assert leave.is_active_on(date(2026, 8, 10)) is True
        assert leave.is_active_on(date(2026, 9, 1)) is False

    def test_self_approval_blocked(self):
        # Maker also granted approval perms but still cannot approve own request.
        self.maker.role.permissions += ["workflow.approve", "hr.leave.approve"]
        self.maker.role.save(update_fields=["permissions"])
        leave = self._request(requested_by=self.maker)
        with self.assertRaises(PermissionDenied):
            LeaveService.decide(leave=leave, actor=self.maker, approve=True)
        leave.refresh_from_db()
        assert leave.status == LeaveRequest.Status.PENDING

    def test_rejection_marks_leave_rejected(self):
        leave = self._request()
        LeaveService.decide(leave=leave, actor=self.checker, approve=False, note="Equipe reduzida")
        leave.refresh_from_db()
        assert leave.status == LeaveRequest.Status.REJECTED
        assert leave.is_active_on(date(2026, 8, 10)) is False

    def test_overlapping_leave_guarded(self):
        self._request(start=date(2026, 8, 1), end=date(2026, 8, 15))
        with self.assertRaises(ValidationError):
            self._request(start=date(2026, 8, 10), end=date(2026, 8, 20))
