"""
ADT P2-2 — Higienização fecha o ciclo do leito.

A discharge/transfer frees a bed to ``higienizacao`` (dirty); until now nothing
returned it to ``livre``. This closes the cycle: ``release_from_housekeeping``
cleans a dirty bed back to ``livre`` and every status transition (dirty on
discharge/transfer, clean on release) writes one append-only ``BedStatusEvent``
so the bed's housekeeping cycle is auditable end to end.

RBAC: the ``release`` action requires ``beds.housekeeping`` (nursing/limpeza
duty, distinct from ``beds.manage`` structure management); the bed-status event
log is read-only (``beds.read``).
"""

from django.core.exceptions import ValidationError as DjangoValidationError

from apps.core.models import Role, User
from apps.emr.models import Bed, BedStatusEvent
from apps.emr.services import adt as adt_service

from .test_adt_admission import AdmissionTestBase

BASE = "/api/v1"


class HousekeepingTestBase(AdmissionTestBase):
    def setUp(self):
        super().setUp()
        self.housekeeping_role = Role.objects.create(
            name="higienizacao", permissions=["beds.read", "beds.housekeeping"]
        )
        self.housekeeper = User.objects.create_user(
            email="hk@t.com", password="pw", role=self.housekeeping_role
        )

    def _admit(self, patient=None, bed=None):
        return adt_service.admit(
            patient=patient or self.patient,
            bed=bed or self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )


# ─── Service-level ────────────────────────────────────────────────────────────


class TestReleaseService(HousekeepingTestBase):
    def test_release_returns_dirty_bed_to_livre_and_logs_event(self):
        admission = self._admit()
        adt_service.discharge(admission=admission, disposition="alta_melhorada")
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.HIGIENIZACAO

        released = adt_service.release_from_housekeeping(bed=self.bed, actor=self.housekeeper)
        assert released.status == Bed.Status.LIVRE
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.LIVRE
        ev = BedStatusEvent.objects.filter(
            bed=self.bed, from_status=Bed.Status.HIGIENIZACAO, to_status=Bed.Status.LIVRE
        ).get()
        assert ev.actor_id == self.housekeeper.id

    def test_release_rejects_non_housekeeping_bed(self):
        # A livre bed is not in higienizacao → cannot be "released".
        assert self.bed.status == Bed.Status.LIVRE
        try:
            adt_service.release_from_housekeeping(bed=self.bed)
            raise AssertionError("expected release of non-dirty bed to raise")
        except DjangoValidationError:
            pass
        assert not BedStatusEvent.objects.filter(to_status=Bed.Status.LIVRE).exists()

    def test_discharge_logs_bed_status_event(self):
        admission = self._admit()
        adt_service.discharge(admission=admission, disposition="alta_melhorada")
        ev = BedStatusEvent.objects.filter(
            bed=self.bed, from_status=Bed.Status.OCUPADO, to_status=Bed.Status.HIGIENIZACAO
        ).get()
        assert ev.bed_id == self.bed.id

    def test_transfer_logs_bed_status_event_for_freed_bed(self):
        admission = self._admit()
        dest = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-B", bed_type=self.bed_type
        )
        adt_service.transfer(admission, dest)
        # Origin bed logged ocupado→higienizacao.
        assert BedStatusEvent.objects.filter(
            bed=self.bed, from_status=Bed.Status.OCUPADO, to_status=Bed.Status.HIGIENIZACAO
        ).exists()

    def test_full_cycle_ocupado_higienizacao_livre_is_auditable(self):
        admission = self._admit()
        adt_service.discharge(admission=admission, disposition="alta_melhorada")
        adt_service.release_from_housekeeping(bed=self.bed, actor=self.housekeeper)
        transitions = list(
            BedStatusEvent.objects.filter(bed=self.bed).values_list("from_status", "to_status")
        )
        assert transitions == [
            (Bed.Status.OCUPADO, Bed.Status.HIGIENIZACAO),
            (Bed.Status.HIGIENIZACAO, Bed.Status.LIVRE),
        ]


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestReleaseAPI(HousekeepingTestBase):
    def _dirty_bed(self):
        admission = self._admit()
        adt_service.discharge(admission=admission, disposition="alta_melhorada")
        self.bed.refresh_from_db()
        return self.bed

    def test_release_requires_housekeeping_permission(self):
        bed = self._dirty_bed()
        # discharger has adt.* + beds.read but NOT beds.housekeeping → 403
        forbidden = self._client(self.discharger).post(
            f"{BASE}/beds/{bed.id}/release/", {}, format="json"
        )
        assert forbidden.status_code == 403, forbidden.content
        # housekeeper carries beds.housekeeping → 200
        ok = self._client(self.housekeeper).post(
            f"{BASE}/beds/{bed.id}/release/", {}, format="json"
        )
        assert ok.status_code == 200, ok.content
        bed.refresh_from_db()
        assert bed.status == Bed.Status.LIVRE

    def test_release_non_housekeeping_bed_returns_409(self):
        # self.bed starts livre → release is a conflict.
        resp = self._client(self.housekeeper).post(
            f"{BASE}/beds/{self.bed.id}/release/", {}, format="json"
        )
        assert resp.status_code == 409, resp.content

    def test_bed_status_events_readable_and_filterable(self):
        admission = self._admit()
        adt_service.discharge(admission=admission, disposition="alta_melhorada")
        resp = self._client(self.reader).get(f"{BASE}/bed-status-events/?bed={self.bed.id}")
        assert resp.status_code == 200, resp.content
        rows = self._rows(resp)
        assert len(rows) == 1
        assert rows[0]["to_status"] == Bed.Status.HIGIENIZACAO

    def test_bed_status_events_read_only_no_post(self):
        resp = self._client(self.housekeeper).post(f"{BASE}/bed-status-events/", {}, format="json")
        assert resp.status_code in (403, 405), resp.content
