"""
ADT P2-3 — Isolamento gatilha alocação.

A patient under an isolation precaution (contato/goticula/aerossol/protetor)
must occupy a bed in an isolation room (``Room.isolation=True``). This is enforced
at every allocation point: admit, transfer, and a mid-stay ``set_precaution`` that
revalidates the current bed. ``nenhuma`` imposes no constraint.

RBAC: ``set_precaution`` requires ``adt.transfer`` (same class as moving a
patient); admit/transfer keep their existing gates.
"""

from django.core.exceptions import ValidationError as DjangoValidationError

from apps.core.models import Role, User
from apps.emr.models import Admission, Bed, Room
from apps.emr.services import adt as adt_service

from .test_adt_admission import AdmissionTestBase

BASE = "/api/v1"


class IsolationTestBase(AdmissionTestBase):
    def setUp(self):
        super().setUp()
        # Isolation room + two isolation beds (self.room/self.bed are non-isolation).
        self.iso_room = Room.objects.create(unit=self.unit, name="ISO-1", isolation=True)
        self.iso_bed = Bed.objects.create(
            room=self.iso_room, unit=self.unit, identifier="ISO-1-A", bed_type=self.bed_type
        )
        self.iso_bed2 = Bed.objects.create(
            room=self.iso_room, unit=self.unit, identifier="ISO-1-B", bed_type=self.bed_type
        )
        self.transfer_role = Role.objects.create(
            name="nir", permissions=["adt.admit", "adt.transfer", "beds.read"]
        )
        self.transferer = User.objects.create_user(
            email="nir@t.com", password="pw", role=self.transfer_role
        )

    def _admit(self, bed, precaution=Admission.IsolationPrecaution.NENHUMA):
        return adt_service.admit(
            patient=self.patient,
            bed=bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            isolation_precaution=precaution,
            actor=self.admitter,
        )


# ─── Service-level ────────────────────────────────────────────────────────────


class TestIsolationAdmitService(IsolationTestBase):
    def test_admit_precaution_requires_isolation_room(self):
        try:
            self._admit(self.bed, precaution="contato")
            raise AssertionError("expected admit with precaution to non-iso bed to raise")
        except DjangoValidationError:
            pass
        assert not Admission.objects.exists()
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.LIVRE  # transaction rolled back

    def test_admit_precaution_into_isolation_room_ok(self):
        admission = self._admit(self.iso_bed, precaution="aerossol")
        assert admission.isolation_precaution == "aerossol"
        self.iso_bed.refresh_from_db()
        assert self.iso_bed.status == Bed.Status.OCUPADO

    def test_admit_no_precaution_into_any_room_ok(self):
        admission = self._admit(self.bed, precaution="nenhuma")
        assert admission.current_bed_id == self.bed.id


class TestIsolationTransferService(IsolationTestBase):
    def test_transfer_isolation_patient_to_non_isolation_rejected(self):
        admission = self._admit(self.iso_bed, precaution="contato")
        try:
            adt_service.transfer(admission, self.bed)
            raise AssertionError("expected transfer of iso patient to non-iso bed to raise")
        except DjangoValidationError:
            pass
        admission.refresh_from_db()
        assert admission.current_bed_id == self.iso_bed.id  # unmoved

    def test_transfer_isolation_patient_to_isolation_ok(self):
        admission = self._admit(self.iso_bed, precaution="contato")
        adt_service.transfer(admission, self.iso_bed2)
        admission.refresh_from_db()
        assert admission.current_bed_id == self.iso_bed2.id

    def test_transfer_non_precaution_patient_anywhere_ok(self):
        admission = self._admit(self.bed, precaution="nenhuma")
        adt_service.transfer(admission, self.iso_bed)
        admission.refresh_from_db()
        assert admission.current_bed_id == self.iso_bed.id


class TestSetPrecautionService(IsolationTestBase):
    def test_set_precaution_rejects_when_current_bed_not_isolation(self):
        admission = self._admit(self.bed)  # non-iso bed, no precaution
        try:
            adt_service.set_precaution(admission=admission, isolation_precaution="goticula")
            raise AssertionError("expected set_precaution on non-iso bed to raise")
        except DjangoValidationError:
            pass
        admission.refresh_from_db()
        assert admission.isolation_precaution == "nenhuma"

    def test_set_precaution_ok_when_current_bed_isolation(self):
        admission = self._admit(self.iso_bed)  # iso bed, no precaution yet
        adt_service.set_precaution(admission=admission, isolation_precaution="goticula")
        admission.refresh_from_db()
        assert admission.isolation_precaution == "goticula"

    def test_set_precaution_nenhuma_always_ok(self):
        admission = self._admit(self.iso_bed, precaution="contato")
        adt_service.set_precaution(admission=admission, isolation_precaution="nenhuma")
        admission.refresh_from_db()
        assert admission.isolation_precaution == "nenhuma"


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestIsolationAPI(IsolationTestBase):
    def _admit_payload(self, bed, **kw):
        payload = {
            "patient": str(self.patient.id),
            "bed": str(bed.id),
            "admitting_professional": str(self.prof.id),
            "attending_professional": str(self.prof.id),
            "admission_source": "emergencia",
        }
        payload.update(kw)
        return payload

    def test_admit_precaution_in_normal_room_returns_409(self):
        resp = self._client(self.admitter).post(
            f"{BASE}/admissions/",
            self._admit_payload(self.bed, isolation_precaution="contato"),
            format="json",
        )
        assert resp.status_code == 409, resp.content

    def test_admit_precaution_in_isolation_room_created(self):
        resp = self._client(self.admitter).post(
            f"{BASE}/admissions/",
            self._admit_payload(self.iso_bed, isolation_precaution="contato"),
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.data["isolation_precaution"] == "contato"

    def test_set_precaution_requires_transfer_permission(self):
        admission = self._admit(self.iso_bed)
        # admitter has adt.admit but NOT adt.transfer → 403
        forbidden = self._client(self.admitter).post(
            f"{BASE}/admissions/{admission.id}/set-precaution/",
            {"isolation_precaution": "contato"},
            format="json",
        )
        assert forbidden.status_code == 403, forbidden.content
        # transferer carries adt.transfer → 200
        ok = self._client(self.transferer).post(
            f"{BASE}/admissions/{admission.id}/set-precaution/",
            {"isolation_precaution": "contato"},
            format="json",
        )
        assert ok.status_code == 200, ok.content

    def test_set_precaution_conflict_returns_409(self):
        admission = self._admit(self.bed)  # non-iso bed
        resp = self._client(self.transferer).post(
            f"{BASE}/admissions/{admission.id}/set-precaution/",
            {"isolation_precaution": "contato"},
            format="json",
        )
        assert resp.status_code == 409, resp.content
