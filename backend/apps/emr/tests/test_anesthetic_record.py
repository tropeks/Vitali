"""
CC2 — Ficha Anestésica (registro do ato anestésico intraoperatório).

Covers:
* AnestheticRecord: OneToOne with a SurgicalCase (2nd ficha for the same case
  fails, at the DB and via the API), ASA / technique choices, anesthesia window.
* AnestheticEvent: append-only timeline (droga / vital / evento), ordered by
  timestamp; index (record, timestamp).
* API: AnestheticRecordViewSet + AnestheticEventViewSet — create / list /
  retrieve; RBAC (surgery.read reads, no surgery.manage cannot create); events
  nested read-only on the record; list filters (?case=, ?record=).
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    AnestheticEvent,
    AnestheticRecord,
    OperatingRoom,
    Patient,
    Professional,
    SurgicalCase,
)
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

MANAGE_PERMS = ["surgery.read", "surgery.manage"]
READ_PERMS = ["surgery.read"]


class AnestheticTestBase(TenantTestCase):
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
        self.anesthesiologist = Professional.objects.create(
            user=self.reader,
            council_type="CRM",
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


# ── AnestheticRecord model ─────────────────────────────────────────────────────


class TestAnestheticRecordModel(AnestheticTestBase):
    def test_create_record_for_case(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(
            case=case,
            anesthesiologist=self.anesthesiologist,
            technique=SurgicalCase.AnesthesiaType.GERAL,
            asa_classification=AnestheticRecord.ASAClassification.ASA_II,
            anesthesia_start=timezone.now(),
        )
        assert case.anesthetic_record == rec
        assert rec.technique == "geral"
        assert rec.asa_classification == "II"

    def test_one_record_per_case(self):
        case = self._case()
        AnestheticRecord.objects.create(case=case)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            AnestheticRecord.objects.create(case=case)

    def test_asa_emergency_choice(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(
            case=case,
            asa_classification=AnestheticRecord.ASAClassification.ASA_III_E,
        )
        assert rec.asa_classification == "IIIE"
        assert "emergência" in rec.get_asa_classification_display().lower()

    def test_anesthesia_window(self):
        case = self._case()
        start = timezone.now()
        end = start + timezone.timedelta(hours=2)
        rec = AnestheticRecord.objects.create(case=case, anesthesia_start=start, anesthesia_end=end)
        assert rec.anesthesia_end > rec.anesthesia_start


# ── AnestheticEvent timeline ───────────────────────────────────────────────────


class TestAnestheticEventModel(AnestheticTestBase):
    def test_add_events_ordered_by_timestamp(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(case=case)
        now = timezone.now()
        e_vital = AnestheticEvent.objects.create(
            record=rec,
            kind=AnestheticEvent.Kind.VITAL,
            description="Sinais vitais",
            value="PA 120/80, FC 72",
            timestamp=now + timezone.timedelta(minutes=10),
        )
        e_droga = AnestheticEvent.objects.create(
            record=rec,
            kind=AnestheticEvent.Kind.DROGA,
            description="Propofol",
            dose="2mg/kg",
            timestamp=now,
        )
        e_evento = AnestheticEvent.objects.create(
            record=rec,
            kind=AnestheticEvent.Kind.EVENTO,
            description="Intubação orotraqueal",
            timestamp=now + timezone.timedelta(minutes=20),
        )
        ordered = list(rec.events.all())
        assert ordered == [e_droga, e_vital, e_evento]

    def test_event_kinds(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(case=case)
        for kind in (
            AnestheticEvent.Kind.DROGA,
            AnestheticEvent.Kind.VITAL,
            AnestheticEvent.Kind.EVENTO,
            AnestheticEvent.Kind.VENTILACAO,
        ):
            AnestheticEvent.objects.create(record=rec, kind=kind, description=str(kind))
        assert rec.events.count() == 4


# ── AnestheticRecord API ───────────────────────────────────────────────────────


class TestAnestheticRecordAPI(AnestheticTestBase):
    def test_create_record(self):
        case = self._case()
        resp = self._client(self.manager).post(
            f"{BASE}/anesthetic-records/",
            {
                "case": str(case.id),
                "anesthesiologist": str(self.anesthesiologist.id),
                "technique": SurgicalCase.AnesthesiaType.RAQUI,
                "asa_classification": AnestheticRecord.ASAClassification.ASA_I,
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        rec = AnestheticRecord.objects.get(case=case)
        assert rec.technique == "raqui"
        # created_by stamped from request.user (never client-set).
        assert rec.created_by_id == self.manager.id

    def test_second_record_rejected(self):
        case = self._case()
        AnestheticRecord.objects.create(case=case)
        resp = self._client(self.manager).post(
            f"{BASE}/anesthetic-records/",
            {"case": str(case.id)},
            format="json",
        )
        assert resp.status_code == 400, resp.content

    def test_create_requires_manage(self):
        case = self._case()
        resp = self._client(self.reader).post(
            f"{BASE}/anesthetic-records/",
            {"case": str(case.id)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_reader_can_read(self):
        case = self._case()
        AnestheticRecord.objects.create(case=case)
        resp = self._client(self.reader).get(f"{BASE}/anesthetic-records/?case={case.id}")
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1

    def test_no_perm_cannot_read(self):
        case = self._case()
        AnestheticRecord.objects.create(case=case)
        resp = self._client(self.nobody).get(f"{BASE}/anesthetic-records/")
        assert resp.status_code == 403, resp.content

    def test_retrieve_with_nested_events(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(case=case)
        AnestheticEvent.objects.create(
            record=rec, kind=AnestheticEvent.Kind.DROGA, description="Fentanil", dose="2mcg/kg"
        )
        resp = self._client(self.reader).get(f"{BASE}/anesthetic-records/{rec.id}/")
        assert resp.status_code == 200, resp.content
        assert len(resp.data["events"]) == 1
        assert resp.data["events"][0]["description"] == "Fentanil"


# ── AnestheticEvent API ────────────────────────────────────────────────────────


class TestAnestheticEventAPI(AnestheticTestBase):
    def test_create_event(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(case=case)
        resp = self._client(self.manager).post(
            f"{BASE}/anesthetic-events/",
            {
                "record": str(rec.id),
                "kind": AnestheticEvent.Kind.DROGA,
                "description": "Propofol",
                "dose": "2mg/kg",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        ev = AnestheticEvent.objects.get(record=rec)
        assert ev.dose == "2mg/kg"
        assert ev.recorded_by_id == self.manager.id

    def test_create_event_requires_manage(self):
        case = self._case()
        rec = AnestheticRecord.objects.create(case=case)
        resp = self._client(self.reader).post(
            f"{BASE}/anesthetic-events/",
            {"record": str(rec.id), "kind": AnestheticEvent.Kind.VITAL, "description": "PA"},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_list_filtered_by_record(self):
        case = self._case()
        other = self._case()
        rec = AnestheticRecord.objects.create(case=case)
        rec_other = AnestheticRecord.objects.create(case=other)
        AnestheticEvent.objects.create(record=rec, kind=AnestheticEvent.Kind.DROGA, description="A")
        AnestheticEvent.objects.create(
            record=rec_other, kind=AnestheticEvent.Kind.DROGA, description="B"
        )
        resp = self._client(self.reader).get(f"{BASE}/anesthetic-events/?record={rec.id}")
        assert resp.status_code == 200, resp.content
        assert resp.data["count"] == 1
