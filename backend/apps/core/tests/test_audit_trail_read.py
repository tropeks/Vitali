"""Onda 3 / 3.3 + 3.4 — read-access audit trail + the DPO-facing endpoint.

3.3: ``retrieve`` and a targeted ``list`` (``?patient=``) on an audited
clinical viewset write a ``view_record``/``view_record_list`` row to
``AuditLog`` naming the user, resource type and id.

3.4: ``GET /api/v1/audit-trail/`` is tenant-scoped, admin-only, and read-only.
"""

import datetime

from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.emr.models import Encounter, Patient, Prescription, Professional
from apps.test_utils import TenantTestCase

BASE = "/api/v1"


class AuditTrailReadTestBase(TenantTestCase):
    def setUp(self):
        self.clinical_role = Role.objects.create(
            name="medico", permissions=["emr.read", "emr.write"]
        )
        self.admin_role = Role.objects.create(name="admin", permissions=["admin"], is_system=True)
        self.clinician = User.objects.create_user(
            email="medico@t.com", password="pw", role=self.clinical_role
        )
        self.admin = User.objects.create_user(
            email="admin@t.com", password="pw", role=self.admin_role
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Auditado",
            cpf="99988877766",
            birth_date=datetime.date(1980, 1, 1),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=self.clinician, council_type="CRM", council_number="1", council_state="SP"
        )
        from django.utils import timezone

        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional, encounter_date=timezone.now()
        )
        self.prescription = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c


class TestReadAccessIsAudited(AuditTrailReadTestBase):
    def test_retrieve_writes_view_record(self):
        AuditLog.objects.all().delete()
        resp = self._client(self.clinician).get(f"{BASE}/prescriptions/{self.prescription.id}/")
        assert resp.status_code == 200, resp.content

        log = AuditLog.objects.get(action="view_record", resource_type="Prescription")
        assert log.user_id == self.clinician.id
        assert log.resource_id == str(self.prescription.id)

    def test_list_without_targeted_filter_is_not_audited(self):
        AuditLog.objects.all().delete()
        resp = self._client(self.clinician).get(f"{BASE}/prescriptions/")
        assert resp.status_code == 200, resp.content
        assert not AuditLog.objects.filter(action="view_record_list").exists()

    def test_list_filtered_by_patient_is_audited_with_criterion_not_result(self):
        AuditLog.objects.all().delete()
        resp = self._client(self.clinician).get(
            f"{BASE}/prescriptions/", {"patient": str(self.patient.id)}
        )
        assert resp.status_code == 200, resp.content

        log = AuditLog.objects.get(action="view_record_list", resource_type="Prescription")
        assert log.user_id == self.clinician.id
        assert log.resource_id == str(self.patient.id)
        assert log.new_data == {"patient": str(self.patient.id)}
        # The criterion is logged, not the response body.
        assert "items" not in (log.new_data or {})


class TestAuditTrailEndpoint(AuditTrailReadTestBase):
    def setUp(self):
        super().setUp()
        self.own_log = AuditLog.objects.create(
            user=self.clinician,
            action="view_record",
            resource_type="Patient",
            resource_id=str(self.patient.id),
            new_data={"should": "not leak"},
        )
        self.other_tenant_log = AuditLog.objects.create(
            user=None,
            action="view_record",
            resource_type="Patient",
            resource_id=str(self.patient.id),
            schema_name="a_different_clinic_schema",
        )

    def test_admin_sees_only_current_tenant_rows(self):
        resp = self._client(self.admin).get(f"{BASE}/audit-trail/")
        assert resp.status_code == 200, resp.content
        ids = {row["id"] for row in resp.data["results"]}
        assert self.own_log.id in ids
        assert self.other_tenant_log.id not in ids

    def test_response_never_exposes_old_data_or_new_data(self):
        resp = self._client(self.admin).get(f"{BASE}/audit-trail/")
        assert resp.status_code == 200, resp.content
        for row in resp.data["results"]:
            assert "old_data" not in row
            assert "new_data" not in row

    def test_patient_filter(self):
        resp = self._client(self.admin).get(
            f"{BASE}/audit-trail/", {"patient": str(self.patient.id)}
        )
        assert resp.status_code == 200, resp.content
        ids = {row["id"] for row in resp.data["results"]}
        assert self.own_log.id in ids

    def test_non_admin_is_forbidden(self):
        resp = self._client(self.clinician).get(f"{BASE}/audit-trail/")
        assert resp.status_code == 403, resp.content

    def test_unauthenticated_is_rejected(self):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = client.get(f"{BASE}/audit-trail/")
        assert resp.status_code in (401, 403)

    def test_endpoint_has_no_write_methods(self):
        client = self._client(self.admin)
        resp = client.post(f"{BASE}/audit-trail/", {}, format="json")
        assert resp.status_code == 405
        resp = client.delete(f"{BASE}/audit-trail/")
        assert resp.status_code == 405
