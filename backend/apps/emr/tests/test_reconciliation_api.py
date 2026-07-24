"""Sprint M1-S3 — REST contract for reconciliation + order-set surfaces.

For each surface: 201 on create (emr.write) writing an audit row, list scoped by
query param (emr.read), 403 without emr.write, 401 unauthenticated. Plus the
order-set maker-checker flow end-to-end over HTTP (submit → approve → apply).
"""

from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.emr.models import (
    AppliedOrder,
    Encounter,
    MedicationReconciliation,
    OrderSet,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase


class _APIBase(TenantTestCase):
    def setUp(self):
        self.rw_role = Role.objects.create(
            name="recon_rw",
            permissions=["emr.read", "emr.write", "workflow.request"],
        )
        self.ro_role = Role.objects.create(name="recon_ro", permissions=["emr.read"])
        self.approver_role = Role.objects.create(
            name="recon_approver", permissions=["workflow.approve", "emr.order_set_approve"]
        )
        self.rw_user = User.objects.create_user(
            email="recon_rw@t.com", password="pw", role=self.rw_role
        )
        self.ro_user = User.objects.create_user(
            email="recon_ro@t.com", password="pw", role=self.ro_role
        )
        self.approver = User.objects.create_user(
            email="recon_ap@t.com", password="pw", role=self.approver_role
        )
        self.patient = Patient.objects.create(
            full_name="API Recon", birth_date="1975-01-01", gender="M", cpf="12312312312"
        )
        self.prof = Professional.objects.create(
            user=self.rw_user, council_type="CRM", council_number="4040", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.prof, chief_complaint="Internação"
        )

    def _client(self, user=None):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        if user is not None:
            c.force_authenticate(user=user)
        return c


class TestMedicationReconciliationAPI(_APIBase):
    URL = "/api/v1/medication-reconciliations/"

    def _payload(self):
        return {
            "patient": str(self.patient.id),
            "encounter": str(self.encounter.id),
            "moment": "admission",
            "items": [
                {
                    "medication_name": "Losartana 50mg",
                    "action": "continue",
                    "reason": "Manter.",
                },
                {"medication_name": "Ibuprofeno", "action": "stop", "reason": "Risco renal."},
            ],
        }

    def test_create_returns_201_with_items_and_audits(self):
        resp = self._client(self.rw_user).post(self.URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(resp.data["items"]), 2)
        self.assertEqual(MedicationReconciliation.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="medication_reconciliation_create").exists())

    def test_list_scoped_by_encounter(self):
        self._client(self.rw_user).post(self.URL, self._payload(), format="json")
        resp = self._client(self.ro_user).get(self.URL, {"encounter": str(self.encounter.id)})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if "results" in resp.data else resp.data
        self.assertEqual(len(rows), 1)

    def test_complete_action_freezes_and_audits(self):
        create = self._client(self.rw_user).post(self.URL, self._payload(), format="json")
        recon_id = create.data["id"]
        resp = self._client(self.rw_user).post(f"{self.URL}{recon_id}/complete/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "completed")
        self.assertTrue(
            AuditLog.objects.filter(action="medication_reconciliation_complete").exists()
        )

    def test_write_forbidden_without_emr_write(self):
        resp = self._client(self.ro_user).post(self.URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self._client().get(self.URL).status_code, 401)


class TestOrderSetAPI(_APIBase):
    URL = "/api/v1/order-sets/"

    def _payload(self, key="dka-bundle"):
        return {
            "key": key,
            "name": "Bundle CAD",
            "items": [
                {"order_type": "lab", "label": "Glicemia", "sequence": 1},
                {"order_type": "medication", "label": "Insulina regular IV", "sequence": 2},
            ],
        }

    def test_create_returns_201_and_audits(self):
        resp = self._client(self.rw_user).post(self.URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(resp.data["items"]), 2)
        self.assertEqual(resp.data["status"], "draft")
        self.assertTrue(AuditLog.objects.filter(action="order_set_create").exists())

    def test_list_scoped_by_key(self):
        self._client(self.rw_user).post(self.URL, self._payload(key="a"), format="json")
        self._client(self.rw_user).post(self.URL, self._payload(key="b"), format="json")
        resp = self._client(self.ro_user).get(self.URL, {"key": "a"})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if "results" in resp.data else resp.data
        self.assertEqual(len(rows), 1)

    def test_write_forbidden_without_emr_write(self):
        resp = self._client(self.ro_user).post(self.URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self._client().get(self.URL).status_code, 401)

    def test_submit_and_apply_flow(self):
        create = self._client(self.rw_user).post(self.URL, self._payload(), format="json")
        os_id = create.data["id"]

        # Applying a draft is rejected.
        apply_draft = self._client(self.rw_user).post(
            f"{self.URL}{os_id}/apply/", {"encounter": str(self.encounter.id)}, format="json"
        )
        self.assertEqual(apply_draft.status_code, 409)

        submit = self._client(self.rw_user).post(f"{self.URL}{os_id}/submit/")
        self.assertEqual(submit.status_code, 202, submit.data)

        # Approve via governance service (different actor — maker-checker).
        order_set = OrderSet.objects.get(pk=os_id)
        from apps.governance.services import ApprovalService

        ApprovalService.decide(approval_id=order_set.approval_id, actor=self.approver, approve=True)

        apply_ok = self._client(self.rw_user).post(
            f"{self.URL}{os_id}/apply/", {"encounter": str(self.encounter.id)}, format="json"
        )
        self.assertEqual(apply_ok.status_code, 201, apply_ok.data)
        self.assertEqual(len(apply_ok.data["orders"]), 2)
        self.assertEqual(AppliedOrder.objects.filter(encounter=self.encounter).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="order_set_apply").exists())
