"""Orchestrator + flywheel tests for the no-show wedge (PR N2).

Covers flag-OFF no-op, evaluate_window persistence + inert (<5 terminal), the
leakage guards (cancelled excluded from history; only past terminal counts),
override-preservation, the 4-way grading, idempotency, and a loose N+1 guard on
the batch history resolution. The pure scoring is covered in test_no_show_checker.
"""

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.core.models import FeatureFlag, User
from apps.emr.models import Appointment, NoShowRisk, Patient, Professional
from apps.emr.services.no_show import NoShowService
from apps.test_utils import TenantTestCase


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag(True)
        self.now = timezone.now()
        self.user = User.objects.create_user(
            email="ns@test.com", full_name="Recepção", password="Str0ng!Pass#2024"
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="1", council_state="SP"
        )
        self._slot = 0

    def _set_flag(self, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="no_show_prediction",
            defaults={"is_enabled": enabled},
        )

    def _patient(self, cpf):
        return Patient.objects.create(
            full_name=f"P{cpf}", birth_date="1980-01-01", gender="M", cpf=cpf
        )

    def _appt(self, patient, *, offset_days, status, **kw):
        # Space slots by hours (with a 30-min duration) so the Appointment.clean()
        # overlap validator never trips, and start_times stay distinct
        # (unique_together professional+start_time).
        self._slot += 1
        start = self.now + datetime.timedelta(days=offset_days, hours=self._slot)
        return Appointment.objects.create(
            patient=patient,
            professional=self.prof,
            start_time=start,
            end_time=start + datetime.timedelta(minutes=30),
            status=status,
            type=kw.get("type", "consultation"),
            source=kw.get("source", "receptionist"),
            whatsapp_confirmed=kw.get("whatsapp_confirmed", False),
            whatsapp_reminder_sent=kw.get("whatsapp_reminder_sent", False),
        )

    def _history(self, patient, *, no_shows, completed):
        for _ in range(no_shows):
            self._appt(patient, offset_days=-30, status="no_show")
        for _ in range(completed):
            self._appt(patient, offset_days=-30, status="completed")


class TestEvaluate(_Base):
    def test_flag_off_is_noop(self):
        self._set_flag(False)
        p = self._patient("11122233300")
        self._history(p, no_shows=4, completed=4)
        self._appt(p, offset_days=2, status="scheduled")
        NoShowService().evaluate_window(now=self.now)
        assert NoShowRisk.objects.count() == 0

    def test_scores_upcoming_with_history(self):
        p = self._patient("11122233301")
        self._history(p, no_shows=4, completed=4)  # 8 terminal, 50% raw
        appt = self._appt(p, offset_days=2, status="scheduled")
        NoShowService().evaluate_window(now=self.now)
        risk = NoShowRisk.objects.get(appointment=appt)
        assert risk.band in ("low", "medium", "high")
        assert risk.outcome == NoShowRisk.Outcome.PENDING

    def test_inert_patient_below_min_sample_no_row(self):
        p = self._patient("11122233302")
        self._history(p, no_shows=1, completed=2)  # 3 terminal < 5 → inert
        self._appt(p, offset_days=2, status="scheduled")
        NoShowService().evaluate_window(now=self.now)
        assert NoShowRisk.objects.count() == 0

    def test_cancelled_excluded_from_history(self):
        # 10 cancelled + nothing terminal → still inert (cancelled not counted).
        p = self._patient("11122233303")
        for _ in range(10):
            self._appt(p, offset_days=-10, status="cancelled")
        self._appt(p, offset_days=2, status="scheduled")
        NoShowService().evaluate_window(now=self.now)
        assert NoShowRisk.objects.count() == 0

    def test_override_preserved_when_band_unchanged(self):
        p = self._patient("11122233304")
        self._history(p, no_shows=4, completed=4)
        appt = self._appt(p, offset_days=2, status="scheduled")
        svc = NoShowService()
        svc.evaluate_window(now=self.now)
        risk = NoShowRisk.objects.get(appointment=appt)
        risk.acknowledge(self.user, note="liguei pro paciente")
        band_before = risk.band
        # Re-evaluate: same history → same band → ack must stand.
        svc.evaluate_window(now=self.now)
        risk.refresh_from_db()
        assert risk.status == NoShowRisk.Status.ACKNOWLEDGED
        assert risk.band == band_before

    def test_batch_history_not_n_plus_1(self):
        # Many patients/appointments; the Appointment reads must NOT scale per
        # appointment (no N+1 in history resolution) — count only emr_appointment
        # SELECTs (robust against django-tenants SET search_path / savepoint noise).
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(4):
            p = self._patient(f"2220000000{i}")
            self._history(p, no_shows=3, completed=3)
            self._appt(p, offset_days=1, status="scheduled")
            self._appt(p, offset_days=3, status="confirmed")

        with CaptureQueriesContext(connection) as ctx:
            NoShowService().evaluate_window(now=self.now)
        appt_selects = [
            q["sql"]
            for q in ctx.captured_queries
            if 'FROM "emr_appointment"' in q["sql"]
            and q["sql"].lstrip().upper().startswith("SELECT")
        ]
        # Exactly two: the upcoming window + the ordered terminal history. Constant
        # regardless of the number of patients/appointments.
        assert len(appt_selects) == 2, f"expected 2 appointment reads, got {len(appt_selects)}"


class TestGrading(_Base):
    def _risk_on(self, *, status, band):
        p = self._patient(f"33300000{self._slot:02d}")
        appt = self._appt(p, offset_days=-1, status=status)  # already past
        return NoShowRisk.objects.create(
            appointment=appt, score="0.6000", band=band, engine_version="noshow-n1"
        )

    def test_no_show_high_is_true_positive(self):
        r = self._risk_on(status="no_show", band="high")
        NoShowService().grade_predictions(now=self.now)
        r.refresh_from_db()
        assert r.outcome == NoShowRisk.Outcome.TRUE_POSITIVE
        assert r.graded_at is not None

    def test_completed_high_is_false_positive(self):
        r = self._risk_on(status="completed", band="medium")
        NoShowService().grade_predictions(now=self.now)
        r.refresh_from_db()
        assert r.outcome == NoShowRisk.Outcome.FALSE_POSITIVE

    def test_no_show_low_is_false_negative(self):
        r = self._risk_on(status="no_show", band="low")
        NoShowService().grade_predictions(now=self.now)
        r.refresh_from_db()
        assert r.outcome == NoShowRisk.Outcome.FALSE_NEGATIVE

    def test_completed_low_is_true_negative(self):
        r = self._risk_on(status="completed", band="low")
        NoShowService().grade_predictions(now=self.now)
        r.refresh_from_db()
        assert r.outcome == NoShowRisk.Outcome.TRUE_NEGATIVE

    def test_cancelled_stays_pending(self):
        r = self._risk_on(status="cancelled", band="high")
        NoShowService().grade_predictions(now=self.now)
        r.refresh_from_db()
        assert r.outcome == NoShowRisk.Outcome.PENDING
        assert r.graded_at is None

    def test_grading_is_idempotent(self):
        r = self._risk_on(status="no_show", band="high")
        svc = NoShowService()
        svc.grade_predictions(now=self.now)
        counts = svc.grade_predictions(now=self.now)  # second run grades nothing
        assert sum(counts.values()) == 0
        r.refresh_from_db()
        assert r.outcome == NoShowRisk.Outcome.TRUE_POSITIVE


class TestServiceTenantContext(TestCase):
    """is_enabled fails closed when no tenant is resolvable (defensive)."""

    def test_is_enabled_false_without_tenant(self):
        # Plain TestCase has no django-tenants connection.tenant → fail closed.
        assert NoShowService.is_enabled() is False
