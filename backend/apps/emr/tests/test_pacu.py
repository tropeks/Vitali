"""
CS2 — SRPA / PACU (recuperação pós-anestésica).

Covers:
* PacuRecord: OneToOne with a SurgicalCase (2nd registro for the same case
  fails, at the DB and via the API), Aldrete admission/discharge, discharge
  destination choices, discharge_criteria_met flag.
* PacuAssessment: append-only timeline (Aldrete + 5 components + pain), ordered
  by assessed_at; index (record, assessed_at).
* API: PacuRecordViewSet + PacuAssessmentViewSet — create / list / retrieve;
  RBAC (surgery.read reads, no surgery.manage cannot create); assessments nested
  read-only on the record; list filters (?case=, ?record=).
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    OperatingRoom,
    PacuAssessment,
    PacuRecord,
    Patient,
    Professional,
    SurgicalCase,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["surgery.read", "surgery.manage"]
READ_PERMS = ["surgery.read"]


class PacuTestBase(TenantTestCase):
    def setUp(self):
        self.manage_role = Role.objects.create(name="gestor_cc", permissions=MANAGE_PERMS)
        self.read_role = Role.objects.create(name="enf_cc", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])
        self.manager = User.objects.create_user(
            email="gestor@t.com", password="pw", role=self.manage_role
        )
        self.reader = User.objects.create_user(
            email="enfcc@t.com", password="pw", role=self.read_role
        )
        self.nobody = User.objects.create_user(
            email="none@t.com", password="pw", role=self.none_role
        )

        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.surgeon = Professional.objects.create(
            user=self.manager,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
        )
        self.nurse = Professional.objects.create(
            user=self.reader,
            council_type="COREN",
            council_number="67890",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Maria Operada", birth_date="1980-01-01", gender="F", cpf="52998224725"
        )
        self.room = OperatingRoom.objects.create(facility=self.facility, code="SO-1", name="Sala 1")

    def _case(self, **kw):
        defaults = {"patient": self.patient, "surgeon": self.surgeon}
        defaults.update(kw)
        return SurgicalCase.objects.create(**defaults)

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c


# ── PacuRecord model ───────────────────────────────────────────────────────────


class TestPacuRecordModel(PacuTestBase):
    def test_create_record_for_case(self):
        case = self._case()
        rec = PacuRecord.objects.create(
            case=case,
            admitted_by=self.nurse,
            admitted_at=timezone.now(),
            aldrete_admission=8,
        )
        assert case.pacu_record == rec
        assert rec.aldrete_admission == 8
        assert rec.discharge_criteria_met is False
        assert rec.discharge_destination == ""

    def test_one_record_per_case(self):
        case = self._case()
        PacuRecord.objects.create(case=case)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PacuRecord.objects.create(case=case)

    def test_discharge_flow(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case, admitted_at=timezone.now(), aldrete_admission=7)
        rec.aldrete_discharge = 10
        rec.discharged_at = timezone.now()
        rec.discharge_destination = PacuRecord.DischargeDestination.ENFERMARIA
        rec.discharge_criteria_met = True
        rec.save()
        rec.refresh_from_db()
        assert rec.discharge_criteria_met is True
        assert rec.discharge_destination == "enfermaria"
        assert rec.aldrete_discharge == 10

    def test_discharge_destinations(self):
        for dest in (
            PacuRecord.DischargeDestination.ENFERMARIA,
            PacuRecord.DischargeDestination.UTI,
            PacuRecord.DischargeDestination.ALTA,
            PacuRecord.DischargeDestination.OBITO,
        ):
            case = self._case()
            rec = PacuRecord.objects.create(case=case, discharge_destination=dest)
            assert rec.discharge_destination == dest.value


# ── PacuAssessment timeline ─────────────────────────────────────────────────────


class TestPacuAssessmentModel(PacuTestBase):
    def test_add_assessments_ordered_by_assessed_at(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        now = timezone.now()
        a_late = PacuAssessment.objects.create(
            record=rec, aldrete_score=9, assessed_at=now + timezone.timedelta(minutes=20)
        )
        a_early = PacuAssessment.objects.create(record=rec, aldrete_score=6, assessed_at=now)
        a_mid = PacuAssessment.objects.create(
            record=rec, aldrete_score=8, assessed_at=now + timezone.timedelta(minutes=10)
        )
        ordered = list(rec.assessments.all())
        assert ordered == [a_early, a_mid, a_late]

    def test_aldrete_components(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        a = PacuAssessment.objects.create(
            record=rec,
            aldrete_score=10,
            consciousness=2,
            respiration=2,
            circulation=2,
            activity=2,
            oxygen=2,
            pain_score=1,
            recorded_by=self.nurse,
        )
        assert a.consciousness + a.respiration + a.circulation + a.activity + a.oxygen == 10
        assert a.aldrete_score == 10
        assert a.pain_score == 1

    def test_aggregate_only_assessment(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        a = PacuAssessment.objects.create(record=rec, aldrete_score=7, notes="estável, sonolento")
        assert a.aldrete_score == 7
        assert a.consciousness is None


# ── PacuRecord API ───────────────────────────────────────────────────────────


class TestPacuRecordAPI(PacuTestBase):
    def test_create_record(self):
        case = self._case()
        resp = self._client(self.manager).post(
            f"{BASE}/pacu-records/",
            {
                "case": str(case.id),
                "admitted_by": str(self.nurse.id),
                "aldrete_admission": 8,
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        rec = PacuRecord.objects.get(case=case)
        assert rec.aldrete_admission == 8
        # created_by stamped from request.user (never client-set).
        assert rec.created_by_id == self.manager.id

    def test_second_record_rejected(self):
        case = self._case()
        PacuRecord.objects.create(case=case)
        resp = self._client(self.manager).post(
            f"{BASE}/pacu-records/",
            {"case": str(case.id)},
            format="json",
        )
        assert resp.status_code == 400, resp.content

    def test_create_requires_manage(self):
        case = self._case()
        resp = self._client(self.reader).post(
            f"{BASE}/pacu-records/",
            {"case": str(case.id)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_discharge_via_patch(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        resp = self._client(self.manager).patch(
            f"{BASE}/pacu-records/{rec.id}/",
            {
                "discharge_destination": PacuRecord.DischargeDestination.UTI,
                "discharge_criteria_met": True,
                "aldrete_discharge": 9,
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        rec.refresh_from_db()
        assert rec.discharge_destination == "uti"
        assert rec.discharge_criteria_met is True

    def test_reader_can_read(self):
        case = self._case()
        PacuRecord.objects.create(case=case)
        resp = self._client(self.reader).get(f"{BASE}/pacu-records/?case={case.id}")
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1

    def test_no_perm_cannot_read(self):
        case = self._case()
        PacuRecord.objects.create(case=case)
        resp = self._client(self.nobody).get(f"{BASE}/pacu-records/")
        assert resp.status_code == 403, resp.content

    def test_retrieve_with_nested_assessments(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        PacuAssessment.objects.create(record=rec, aldrete_score=9, notes="pronto p/ alta")
        resp = self._client(self.reader).get(f"{BASE}/pacu-records/{rec.id}/")
        assert resp.status_code == 200, resp.content
        assert len(resp.data["assessments"]) == 1
        assert resp.data["assessments"][0]["aldrete_score"] == 9


# ── PacuAssessment API ─────────────────────────────────────────────────────────


class TestPacuAssessmentAPI(PacuTestBase):
    def test_create_assessment(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        resp = self._client(self.manager).post(
            f"{BASE}/pacu-assessments/",
            {
                "record": str(rec.id),
                "aldrete_score": 8,
                "consciousness": 2,
                "respiration": 2,
                "circulation": 1,
                "activity": 2,
                "oxygen": 1,
                "pain_score": 2,
                "recorded_by": str(self.nurse.id),
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        a = PacuAssessment.objects.get(record=rec)
        assert a.aldrete_score == 8
        assert a.recorded_by_id == self.nurse.id

    def test_create_assessment_requires_manage(self):
        case = self._case()
        rec = PacuRecord.objects.create(case=case)
        resp = self._client(self.reader).post(
            f"{BASE}/pacu-assessments/",
            {"record": str(rec.id), "aldrete_score": 7},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_list_filtered_by_record(self):
        case = self._case()
        other = self._case()
        rec = PacuRecord.objects.create(case=case)
        rec_other = PacuRecord.objects.create(case=other)
        PacuAssessment.objects.create(record=rec, aldrete_score=8)
        PacuAssessment.objects.create(record=rec_other, aldrete_score=9)
        resp = self._client(self.reader).get(f"{BASE}/pacu-assessments/?record={rec.id}")
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1
