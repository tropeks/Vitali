"""
L3 — ADT transferência + censo/ocupação tests.

Transfer moves an active admission to another bed through the
``apps.emr.services.adt.transfer`` service (never raw save): the old bed goes to
``higienizacao``, the new bed to ``ocupado``, ``current_bed`` follows, and one
append-only ``transfer`` AdmissionEvent (from+to bed) is written — all atomic.
Transfer to an occupied/blocked bed is rejected (409 at the API). ``adt.transfer``
is required (403 without it).

Census/ocupação (``apps.emr.services.census``): ``unit_occupancy`` reports total
beds, per-status counts, operational beds (excludes interditado/bloqueado) and the
occupancy_rate (ocupado / operational); ``census`` lists active admissions with
patient + current bed + LOS (whole hours). The ``beds/board/`` endpoint returns the
unit → room → bed tree with the occupying patient; ``admissions/census/`` returns
per-unit occupancy + the active-census list. Both gated ``beds.read``.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BedType, Role, User
from apps.emr.models import (
    AdmissionEvent,
    Bed,
    InpatientUnit,
    Patient,
    Professional,
    Room,
)
from apps.emr.services import adt as adt_service
from apps.emr.services import census as census_service
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

TRANSFER_PERMS = ["adt.admit", "adt.transfer", "beds.read"]
ADMIT_ONLY_PERMS = ["adt.admit", "beds.read"]
READ_PERMS = ["beds.read"]


class TransferCensusTestBase(TenantTestCase):
    def setUp(self):
        self.transfer_role = Role.objects.create(name="enfermeiro_nir", permissions=TRANSFER_PERMS)
        self.admit_role = Role.objects.create(name="recepcao_interna", permissions=ADMIT_ONLY_PERMS)
        self.read_role = Role.objects.create(name="leitor", permissions=READ_PERMS)

        self.transferer = User.objects.create_user(
            email="nir@t.com", password="pw", role=self.transfer_role
        )
        self.admitter = User.objects.create_user(
            email="rec@t.com", password="pw", role=self.admit_role
        )
        self.reader = User.objects.create_user(email="rd@t.com", password="pw", role=self.read_role)

        self.prof = Professional.objects.create(
            user=self.transferer,
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
        self.bed2 = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-B", bed_type=self.bed_type
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

    def _admit(self, bed=None):
        return adt_service.admit(
            patient=self.patient,
            bed=bed or self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )


# ─── Transfer service ─────────────────────────────────────────────────────────


class TestTransferService(TransferCensusTestBase):
    def test_transfer_moves_patient_between_beds_and_writes_event(self):
        admission = self._admit()
        moved = adt_service.transfer(
            admission, self.bed2, actor=self.transferer, reason="isolamento"
        )
        assert moved.current_bed_id == self.bed2.id
        self.bed.refresh_from_db()
        self.bed2.refresh_from_db()
        assert self.bed.status == Bed.Status.HIGIENIZACAO
        assert self.bed2.status == Bed.Status.OCUPADO
        ev = AdmissionEvent.objects.filter(
            admission=admission, event_type=AdmissionEvent.EventType.TRANSFER
        ).get()
        assert ev.from_bed_id == self.bed.id
        assert ev.to_bed_id == self.bed2.id
        assert ev.actor_id == self.transferer.id
        assert ev.reason == "isolamento"

    def test_transfer_to_reserved_bed_allowed(self):
        admission = self._admit()
        self.bed2.status = Bed.Status.RESERVADO
        self.bed2.save()
        moved = adt_service.transfer(admission, self.bed2, actor=self.transferer)
        self.bed2.refresh_from_db()
        assert moved.current_bed_id == self.bed2.id
        assert self.bed2.status == Bed.Status.OCUPADO

    def test_transfer_to_occupied_bed_rejected(self):
        admission = self._admit()
        self.bed2.status = Bed.Status.OCUPADO
        self.bed2.save()
        try:
            adt_service.transfer(admission, self.bed2, actor=self.transferer)
            raise AssertionError("expected transfer to occupied bed to raise")
        except DjangoValidationError:
            pass
        # Nothing moved; no transfer event.
        admission.refresh_from_db()
        assert admission.current_bed_id == self.bed.id
        assert not AdmissionEvent.objects.filter(
            event_type=AdmissionEvent.EventType.TRANSFER
        ).exists()

    def test_transfer_to_same_bed_rejected(self):
        admission = self._admit()
        try:
            adt_service.transfer(admission, self.bed, actor=self.transferer)
            raise AssertionError("expected transfer to same bed to raise")
        except DjangoValidationError:
            pass

    def test_transfer_requires_active_admission(self):
        admission = self._admit()
        adt_service.discharge(
            admission=admission, disposition="alta_melhorada", actor=self.transferer
        )
        try:
            adt_service.transfer(admission, self.bed2, actor=self.transferer)
            raise AssertionError("expected transfer on discharged admission to raise")
        except DjangoValidationError:
            pass


# ─── Transfer API + RBAC ──────────────────────────────────────────────────────


class TestTransferAPI(TransferCensusTestBase):
    def test_transfer_permission_can_transfer(self):
        admission = self._admit()
        resp = self._client(self.transferer).post(
            f"{BASE}/admissions/{admission.id}/transfer/",
            {"to_bed": str(self.bed2.id), "reason": "NIR"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        admission.refresh_from_db()
        assert admission.current_bed_id == self.bed2.id

    def test_transfer_without_permission_forbidden(self):
        admission = self._admit()
        resp = self._client(self.admitter).post(
            f"{BASE}/admissions/{admission.id}/transfer/",
            {"to_bed": str(self.bed2.id)},
            format="json",
        )
        assert resp.status_code == 403, resp.content

    def test_transfer_to_occupied_bed_returns_conflict(self):
        admission = self._admit()
        self.bed2.status = Bed.Status.BLOQUEADO
        self.bed2.save()
        resp = self._client(self.transferer).post(
            f"{BASE}/admissions/{admission.id}/transfer/",
            {"to_bed": str(self.bed2.id)},
            format="json",
        )
        assert resp.status_code == 409, resp.content


# ─── Census / occupancy service ───────────────────────────────────────────────


class TestCensusService(TransferCensusTestBase):
    def test_unit_occupancy_counts_and_rate(self):
        # bed (ocupado via admit), bed2 (livre), plus one interditado (non-operational).
        self._admit()
        Bed.objects.create(
            room=self.room,
            unit=self.unit,
            identifier="101-X",
            status=Bed.Status.INTERDITADO,
        )
        occ = census_service.unit_occupancy(self.unit)
        assert occ["total_beds"] == 3
        assert occ["status_counts"][Bed.Status.OCUPADO] == 1
        assert occ["status_counts"][Bed.Status.LIVRE] == 1
        assert occ["status_counts"][Bed.Status.INTERDITADO] == 1
        # operational excludes interditado/bloqueado → 2; rate = 1/2.
        assert occ["operational_beds"] == 2
        assert occ["occupied"] == 1
        assert abs(occ["occupancy_rate"] - 0.5) < 1e-9

    def test_census_lists_active_admissions_with_los(self):
        admission = self._admit()
        admission.admission_datetime = timezone.now() - timezone.timedelta(hours=30)
        admission.save(update_fields=["admission_datetime"])
        rows = census_service.census(unit=self.unit)
        assert len(rows) == 1
        row = rows[0]
        assert row["admission_id"] == str(admission.id)
        assert row["patient"]["id"] == str(self.patient.id)
        assert row["bed"]["id"] == str(self.bed.id)
        assert row["unit"]["id"] == str(self.unit.id)
        assert row["los_hours"] == 30


# ─── Board + census endpoints ─────────────────────────────────────────────────


class TestBoardAndCensusAPI(TransferCensusTestBase):
    def test_board_returns_unit_room_bed_tree_with_patient(self):
        self._admit()
        resp = self._client(self.reader).get(f"{BASE}/beds/board/?unit={self.unit.id}")
        assert resp.status_code == 200, resp.content
        units = resp.data["units"]
        assert len(units) == 1
        unit = units[0]
        assert unit["id"] == str(self.unit.id)
        rooms = unit["rooms"]
        assert len(rooms) == 1
        beds = rooms[0]["beds"]
        occupied = [b for b in beds if b["status"] == Bed.Status.OCUPADO]
        assert len(occupied) == 1
        assert occupied[0]["patient"]["id"] == str(self.patient.id)
        assert occupied[0]["patient"]["name"] == "João Internado"
        free = [b for b in beds if b["status"] == Bed.Status.LIVRE]
        assert free and free[0]["patient"] is None

    def test_board_requires_beds_read(self):
        none_role = Role.objects.create(name="sem_perm", permissions=[])
        nobody = User.objects.create_user(email="no@t.com", password="pw", role=none_role)
        resp = self._client(nobody).get(f"{BASE}/beds/board/")
        assert resp.status_code == 403, resp.content

    def test_census_endpoint_returns_occupancy_and_census(self):
        self._admit()
        resp = self._client(self.reader).get(f"{BASE}/admissions/census/?unit={self.unit.id}")
        assert resp.status_code == 200, resp.content
        assert "occupancy" in resp.data
        assert "census" in resp.data
        occ = resp.data["occupancy"]
        assert len(occ) == 1
        assert occ[0]["occupied"] == 1
        census = resp.data["census"]
        assert len(census) == 1
        assert census[0]["patient"]["id"] == str(self.patient.id)
        assert census[0]["los_hours"] >= 0

    def test_census_endpoint_requires_beds_read(self):
        none_role = Role.objects.create(name="sem_perm2", permissions=[])
        nobody = User.objects.create_user(email="no2@t.com", password="pw", role=none_role)
        resp = self._client(nobody).get(f"{BASE}/admissions/census/")
        assert resp.status_code == 403, resp.content
