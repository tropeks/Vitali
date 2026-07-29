"""
ADT P2-1 — Alta planejada (planned discharge).

Covers the planned-discharge flow driven through ``apps.emr.services.adt``:
``plan_discharge`` sets/updates ``expected_discharge_datetime`` on an active
admission and appends exactly one append-only ``plan_discharge`` event (no bed
movement); rejects a datetime before the admission and a non-active admission.
``planned_discharges`` lists active admissions with a planned discharge, soonest
first, filterable by ``until`` and ``unit``.

RBAC mirrors test_adt_admission.py: the ``plan_discharge`` action requires
``adt.discharge`` (planning the exit is a clinical act); the ``planned`` board is
read-only (``beds.read``).
"""

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from apps.emr.models import Admission, AdmissionEvent, Bed, Patient
from apps.emr.services import adt as adt_service

from .test_adt_admission import AdmissionTestBase

BASE = "/api/v1"


# ─── Service-level ────────────────────────────────────────────────────────────


class TestPlanDischargeService(AdmissionTestBase):
    def _admit(self, patient=None, bed=None):
        return adt_service.admit(
            patient=patient or self.patient,
            bed=bed or self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.admitter,
        )

    def test_plan_discharge_sets_datetime_and_writes_plan_event(self):
        admission = self._admit()
        when = timezone.now() + timedelta(days=2)
        planned = adt_service.plan_discharge(
            admission=admission, expected_discharge_datetime=when, actor=self.discharger
        )
        assert planned.expected_discharge_datetime == when
        # Bed untouched — planning is not a movement.
        self.bed.refresh_from_db()
        assert self.bed.status == Bed.Status.OCUPADO
        ev = AdmissionEvent.objects.filter(
            admission=admission, event_type=AdmissionEvent.EventType.PLAN
        ).get()
        assert ev.from_bed_id is None
        assert ev.to_bed_id is None
        assert ev.actor_id == self.discharger.id

    def test_plan_discharge_can_be_revised(self):
        admission = self._admit()
        first = timezone.now() + timedelta(days=2)
        adt_service.plan_discharge(admission=admission, expected_discharge_datetime=first)
        second = timezone.now() + timedelta(days=4)
        adt_service.plan_discharge(admission=admission, expected_discharge_datetime=second)
        admission.refresh_from_db()
        assert admission.expected_discharge_datetime == second
        # Each revision is audited (append-only): two PLAN events.
        assert (
            AdmissionEvent.objects.filter(
                admission=admission, event_type=AdmissionEvent.EventType.PLAN
            ).count()
            == 2
        )

    def test_plan_discharge_before_admission_rejected(self):
        admission = self._admit()
        past = admission.admission_datetime - timedelta(hours=1)
        try:
            adt_service.plan_discharge(admission=admission, expected_discharge_datetime=past)
            raise AssertionError("expected plan before admission to raise")
        except DjangoValidationError:
            pass
        admission.refresh_from_db()
        assert admission.expected_discharge_datetime is None
        assert not AdmissionEvent.objects.filter(event_type=AdmissionEvent.EventType.PLAN).exists()

    def test_plan_discharge_on_discharged_rejected(self):
        admission = self._admit()
        adt_service.discharge(admission=admission, disposition="alta_melhorada")
        try:
            adt_service.plan_discharge(
                admission=admission,
                expected_discharge_datetime=timezone.now() + timedelta(days=1),
            )
            raise AssertionError("expected plan on discharged admission to raise")
        except DjangoValidationError:
            pass

    def test_planned_discharges_sorted_and_filtered(self):
        # Two active admissions with different planned datetimes.
        far = self._admit()
        adt_service.plan_discharge(
            admission=far, expected_discharge_datetime=timezone.now() + timedelta(days=5)
        )
        other_bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-B", bed_type=self.bed_type
        )
        other_patient = Patient.objects.create(
            full_name="Ana Soon", birth_date="1975-03-03", gender="F", cpf="12345678909"
        )
        soon = self._admit(patient=other_patient, bed=other_bed)
        adt_service.plan_discharge(
            admission=soon, expected_discharge_datetime=timezone.now() + timedelta(days=1)
        )
        # Soonest first.
        rows = list(adt_service.planned_discharges())
        assert [r.id for r in rows] == [soon.id, far.id]
        # ``until`` caps the window: only the soon one is within 2 days.
        capped = list(adt_service.planned_discharges(until=timezone.now() + timedelta(days=2)))
        assert [r.id for r in capped] == [soon.id]
        # ``unit`` scopes by current bed's unit (both share self.unit here).
        assert list(adt_service.planned_discharges(unit=self.unit)) == rows

    def test_planned_discharges_excludes_unplanned_and_discharged(self):
        # Active but no planned discharge → excluded.
        self._admit()
        rows = list(adt_service.planned_discharges())
        assert rows == []


# ─── API + RBAC ───────────────────────────────────────────────────────────────


class TestPlanDischargeAPI(AdmissionTestBase):
    def _admit_api(self):
        resp = self._client(self.admitter).post(
            f"{BASE}/admissions/",
            {
                "patient": str(self.patient.id),
                "bed": str(self.bed.id),
                "admitting_professional": str(self.prof.id),
                "attending_professional": str(self.prof.id),
                "admission_source": "emergencia",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        return resp.data["id"]

    def test_plan_discharge_requires_discharge_permission(self):
        admission_id = self._admit_api()
        when = (timezone.now() + timedelta(days=2)).isoformat()
        # admitter has adt.admit but NOT adt.discharge → 403
        forbidden = self._client(self.admitter).post(
            f"{BASE}/admissions/{admission_id}/plan-discharge/",
            {"expected_discharge_datetime": when},
            format="json",
        )
        assert forbidden.status_code == 403, forbidden.content
        # discharger carries adt.discharge → 200
        ok = self._client(self.discharger).post(
            f"{BASE}/admissions/{admission_id}/plan-discharge/",
            {"expected_discharge_datetime": when},
            format="json",
        )
        assert ok.status_code == 200, ok.content
        admission = Admission.objects.get(pk=admission_id)
        assert admission.expected_discharge_datetime is not None

    def test_plan_discharge_before_admission_returns_409(self):
        admission_id = self._admit_api()
        past = (timezone.now() - timedelta(days=1)).isoformat()
        resp = self._client(self.discharger).post(
            f"{BASE}/admissions/{admission_id}/plan-discharge/",
            {"expected_discharge_datetime": past},
            format="json",
        )
        assert resp.status_code == 409, resp.content

    def test_planned_board_lists_with_beds_read(self):
        admission_id = self._admit_api()
        when = (timezone.now() + timedelta(days=2)).isoformat()
        self._client(self.discharger).post(
            f"{BASE}/admissions/{admission_id}/plan-discharge/",
            {"expected_discharge_datetime": when},
            format="json",
        )
        resp = self._client(self.reader).get(f"{BASE}/admissions/planned/")
        assert resp.status_code == 200, resp.content
        rows = resp.data["planned"]
        assert len(rows) == 1
        assert rows[0]["admission_id"] == admission_id
        assert rows[0]["patient"]["name"] == self.patient.full_name
        assert rows[0]["current_bed"]["identifier"] == self.bed.identifier

    def test_planned_board_requires_beds_read(self):
        resp = self._client(self.nobody).get(f"{BASE}/admissions/planned/")
        assert resp.status_code == 403, resp.content
