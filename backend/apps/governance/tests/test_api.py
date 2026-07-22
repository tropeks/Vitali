from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.test_utils import TenantTestCase

from ..services import ApprovalService


class ApprovalAPIAuthorizationTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        maker_role = Role.objects.create(
            name="workflow-api-maker", permissions=["workflow.read", "workflow.request"]
        )
        checker_role = Role.objects.create(
            name="workflow-api-checker",
            permissions=["workflow.read", "workflow.approve", "finance.approve"],
        )
        unrelated_role = Role.objects.create(
            name="workflow-api-unrelated", permissions=["patients.read"]
        )
        self.maker = User.objects.create_user(email="api-maker@test.local", role=maker_role)
        self.checker = User.objects.create_user(email="api-checker@test.local", role=checker_role)
        self.unrelated = User.objects.create_user(
            email="api-unrelated@test.local", role=unrelated_role
        )
        self.approval = ApprovalService.create(
            requested_by=self.maker,
            workflow_key="purchase-order",
            reference_type="purchase_order",
            reference_id="PO-API",
            title="Pedido API",
            step_permissions=["finance.approve"],
        )

    def test_list_requires_workflow_read(self):
        self.client.force_authenticate(self.unrelated)
        response = self.client.get("/api/v1/governance/approvals/")
        self.assertEqual(response.status_code, 403)

    def test_checker_can_approve_through_api(self):
        self.client.force_authenticate(self.checker)
        response = self.client.post(
            f"/api/v1/governance/approvals/{self.approval.pk}/approve/",
            {"note": "Dentro da alçada"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")

    def test_maker_cannot_approve_through_api(self):
        self.client.force_authenticate(self.maker)
        response = self.client.post(
            f"/api/v1/governance/approvals/{self.approval.pk}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 403)
