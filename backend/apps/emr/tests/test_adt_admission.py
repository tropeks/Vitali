"""
L2 — ADT admissão/internação + ciclo ADT (admit/discharge) tests.

Covers the bed-occupancy state machine driven through the ``apps.emr.services.adt``
service (never raw serializer.save): admit occupies a *livre* leito (bed→ocupado,
Admission status=admitted, one append-only ``admit`` AdmissionEvent); admit on an
already-occupied bed is rejected; discharge frees the bed (→higienizacao), records
the disposition + actual_discharge_datetime, and appends a ``discharge`` event.

RBAC mirrors test_adt_beds_api.py: ``adt.admit`` may admit (403 without it),
``adt.discharge`` is required for the discharge action. A regression test proves
``Encounter.encounter_type`` defaults to ``ambulatorial`` and existing Encounter
creation is unaffected.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BedType, Role, User
from apps.emr.models import (
    Admission,
    AdmissionEvent,
    Bed,
    Encounter,
    InpatientUnit,
    Patient,
    Professional,
    Room,
)
from apps.emr.services import adt as adt_service
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

ADMIT_PERMS = ["adt.admit", "beds.read"]
DISCHARGE_PERMS = ["adt.admit", "adt.discharge", "beds.read"]
READ_PERMS = ["beds.read"]


class AdmissionTestBase(TenantTestCase):
    def setUp(self):
        self.admit_role = Role.objects.create(name="recepcao_interna", permissions=ADMIT_PERMS)
        self.discharge_role = Role.objects.create(
            name="medico_interna", permissions=DISCHARGE_PERMS
        )
        self.read_role = Role.objects.create(name="leitor", permissions=READ_PERMS)
        self.none_role = Role.objects.create(name="sem_perm", permissions=[])

        self.admitter = User.objects.create_user(
            email="adm@t.com", password="pw", role=self.admit_role
        )
        self.discharger = User.objects.create_user(
            email="med@t.com", password="pw", role=self.discharge_role
        )
        self.reader = User.objects.create_user(email="rd@t.com", password="pw", role=self.read_role)
        self.nobody = User.objects.create_user(email="no@t.com", password="pw", role=self.none_role)

        self.prof = Professional.objects.create(
            user=self.discharger,
            council_type="CRM",
            council_number="12345",
            council_state="SP",
        )

        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto tipo II", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala A", code="ALA-A")
        self.room = Room.objects.create(unit=self.unit, name="101")
        self.bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-A", bed_type=self.bed_type
        )
        self.patient = Patient.objects.create(
            full_name="João Internado", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user)
        return c

    @staticmethod
    def _rows(resp):
        return resp.data["results"] if "results" in resp.data else resp.data


# ─── Service-level state machine ──────────────────────────────────────────────


class TestAdmitService(AdmissionTestBase):
    def test_admit_occupies_livre_bed_and_writes_admit_event(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )
        assert admission.status == Admission.Status.ADMITTED
        assert admission.current_bed_id == self.bed.id
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.OCUPADO
        events = AdmissionEvent.objects.filter(admission=admission)
        assert events.count() == 1
        ev = events.get()
        assert ev.event_type == AdmissionEvent.EventType.ADMIT
        assert ev.to_bed_id == self.bed.id
        assert ev.from_bed_id is None
        assert ev.actor_id == self.admitter.id

    def test_admit_on_occupied_bed_rejected(self):
        adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )
        other = Patient.objects.create(
            full_name="Maria", birth_date="1990-02-02", gender="F", cpf="15350946056"
        )
        try:
            adt_service.admit(
                patient=other,
                bed=self.bed,
                admitting_professional=self.prof,
                attending_professional=self.prof,
                admission_source="ambulatorio",
                actor=self.admitter,
            )
            raise AssertionError("expected admit on occupied bed to raise")
        except DjangoValidationError:
            pass
        # No second admission / no stray event created.
        assert Admission.objects.filter(status=Admission.Status.ADMITTED).count() == 1
        assert AdmissionEvent.objects.count() == 1

    def test_admit_reserved_bed_allowed(self):
        self.bed.status = Bed.Status.RESERVADO
        self.bed.save()
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="centro_cirurgico",
            actor=self.admitter,
        )
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.OCUPADO
        assert admission.status == Admission.Status.ADMITTED


class TestDischargeService(AdmissionTestBase):
    def test_discharge_frees_bed_and_writes_discharge_event(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )
        discharged = adt_service.discharge(
            admission=admission,
            disposition="alta_melhorada",
            actor=self.discharger,
        )
        assert discharged.status == Admission.Status.DISCHARGED
        assert discharged.disposition == "alta_melhorada"
        assert discharged.actual_discharge_datetime is not None
        assert discharged.current_bed_id is None
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.HIGIENIZACAO
        ev = AdmissionEvent.objects.filter(
            admission=admission, event_type=AdmissionEvent.EventType.DISCHARGE
        ).get()
        assert ev.from_bed_id == self.bed.id
        assert ev.to_bed_id is None


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestAdmissionAPI(AdmissionTestBase):
    def _admit_payload(self, **kw):
        payload = {
            "patient": str(self.patient.id),
            "bed": str(self.bed.id),
            "admitting_professional": str(self.prof.id),
            "attending_professional": str(self.prof.id),
            "admission_source": "emergencia",
        }
        payload.update(kw)
        return payload

    def test_admit_permission_can_create_admission(self):
        resp = self._client(self.admitter).post(
            f"{BASE}/admissions/", self._admit_payload(), format="json"
        )
        assert resp.status_code == 201, resp.content
        admission = Admission.objects.get(pk=resp.data["id"])
        assert admission.status == Admission.Status.ADMITTED
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.OCUPADO
        assert AdmissionEvent.objects.filter(
            admission=admission, event_type=AdmissionEvent.EventType.ADMIT
        ).exists()

    def test_no_perm_cannot_admit(self):
        resp = self._client(self.reader).post(
            f"{BASE}/admissions/", self._admit_payload(), format="json"
        )
        assert resp.status_code == 403, resp.content
        assert not Admission.objects.exists()

    def test_admit_on_occupied_bed_returns_conflict(self):
        self._client(self.admitter).post(
            f"{BASE}/admissions/", self._admit_payload(), format="json"
        )
        resp = self._client(self.admitter).post(
            f"{BASE}/admissions/", self._admit_payload(), format="json"
        )
        assert resp.status_code == 409, resp.content

    def test_discharge_requires_discharge_permission(self):
        create = self._client(self.admitter).post(
            f"{BASE}/admissions/", self._admit_payload(), format="json"
        )
        admission_id = create.data["id"]
        # admitter has adt.admit but NOT adt.discharge → 403
        forbidden = self._client(self.admitter).post(
            f"{BASE}/admissions/{admission_id}/discharge/",
            {"disposition": "alta_melhorada"},
            format="json",
        )
        assert forbidden.status_code == 403, forbidden.content
        # discharger carries adt.discharge → 200
        ok = self._client(self.discharger).post(
            f"{BASE}/admissions/{admission_id}/discharge/",
            {"disposition": "alta_melhorada"},
            format="json",
        )
        assert ok.status_code == 200, ok.content
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.HIGIENIZACAO

    def test_filter_admissions_by_patient_status_bed(self):
        self._client(self.admitter).post(
            f"{BASE}/admissions/", self._admit_payload(), format="json"
        )
        # admissions list/retrieve are gated adt.admit (not beds.read).
        c = self._client(self.admitter)
        by_patient = c.get(f"{BASE}/admissions/?patient={self.patient.id}")
        assert by_patient.status_code == 200
        assert len(self._rows(by_patient)) == 1
        by_status = c.get(f"{BASE}/admissions/?status=admitted")
        assert len(self._rows(by_status)) == 1
        by_bed = c.get(f"{BASE}/admissions/?bed={self.bed.id}")
        assert len(self._rows(by_bed)) == 1


class TestAdmissionEventAPI(AdmissionTestBase):
    def test_events_are_readable_and_filterable(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )
        resp = self._client(self.reader).get(f"{BASE}/admission-events/?admission={admission.id}")
        assert resp.status_code == 200, resp.content
        rows = self._rows(resp)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "admit"

    def test_events_read_only_no_post(self):
        resp = self._client(self.admitter).post(f"{BASE}/admission-events/", {}, format="json")
        assert resp.status_code in (403, 405), resp.content


# ─── Encounter.encounter_type regression ──────────────────────────────────────


class TestEncounterTypeRegression(AdmissionTestBase):
    def test_encounter_type_defaults_to_ambulatorial(self):
        enc = Encounter.objects.create(
            patient=self.patient,
            professional=self.prof,
            encounter_date=timezone.now(),
        )
        assert enc.encounter_type == "ambulatorial"

    def test_encounter_type_accepts_internacao(self):
        enc = Encounter.objects.create(
            patient=self.patient,
            professional=self.prof,
            encounter_type="internacao",
            encounter_date=timezone.now(),
        )
        enc.refresh_from_db()
        assert enc.encounter_type == "internacao"
