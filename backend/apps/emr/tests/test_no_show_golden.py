"""Golden-validation test suite for the no-show prediction wedge (Sprint S30-01).

Proves:
1. Synthetic dataset band distribution (high / low / inert).
2. Flywheel AuditLog written by grade_predictions.
3. Flag-off → evaluate_window is a true no-op.

Band maths (for reviewer convenience):
  base_rate = (no_shows + α) / (terminal + α + β),   α=2 β=8
  odds       = base_rate / (1 − base_rate)
  score      = odds / (1 + odds)
  MEDIUM_CUTOFF = 0.25, HIGH_CUTOFF = 0.50

High patient  (10 no_shows, 0 completed → terminal=10):
  base_rate = 12/20 = 0.60  → score ≈ 0.6000 → band='high'

Low patient   (0 no_shows, 10 completed → terminal=10):
  base_rate = 2/20  = 0.10  → score ≈ 0.1000 → band='low'

Inert patient (1 no_show, 2 completed → terminal=3 < 5):
  → score_no_show returns None → no NoShowRisk row.
"""

import datetime

from django.utils import timezone

from apps.core.models import AuditLog, FeatureFlag, User
from apps.emr.models import Appointment, NoShowRisk, Patient, Professional
from apps.emr.services.no_show import NoShowService
from apps.test_utils import TenantTestCase


class _Base(TenantTestCase):
    """Shared fixtures for golden tests."""

    def setUp(self):
        self.tenant = self.__class__.tenant
        self._enable_flag()
        self.now = timezone.now()
        self.user = User.objects.create_user(
            email="golden@test.com",
            full_name="Golden Tester",
            password="Str0ng!Pass#2024",
        )
        self.prof = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="999",
            council_state="SP",
        )
        self._slot = 0

    # ── flag helpers ──────────────────────────────────────────────────────────

    def _enable_flag(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="no_show_prediction",
            defaults={"is_enabled": True},
        )

    def _disable_flag(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="no_show_prediction",
            defaults={"is_enabled": False},
        )

    # ── data builders ─────────────────────────────────────────────────────────

    def _patient(self, cpf):
        return Patient.objects.create(
            full_name=f"Golden-{cpf}",
            birth_date="1985-06-15",
            gender="M",
            cpf=cpf,
        )

    def _appt(self, patient, *, offset_days, status, **kw):
        """Create one appointment, spacing start_times by slot to avoid overlaps."""
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
        """Seed past terminal appointments (always offset_days=-30)."""
        for _ in range(no_shows):
            self._appt(patient, offset_days=-30, status="no_show")
        for _ in range(completed):
            self._appt(patient, offset_days=-30, status="completed")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Synthetic dataset band distribution
# ─────────────────────────────────────────────────────────────────────────────


class TestSyntheticDatasetBandDistribution(_Base):
    """evaluate_window assigns the correct band to each synthetic patient archetype."""

    def test_synthetic_dataset_band_distribution(self):
        # (a) Frequent no-show: 10 no_shows, 0 completed → score ≈ 0.60 → high
        high_patient = self._patient("10000000001")
        self._history(high_patient, no_shows=10, completed=0)
        high_appt = self._appt(high_patient, offset_days=2, status="scheduled")

        # (b) Perfect attendance: 0 no_shows, 10 completed → score ≈ 0.10 → low
        low_patient = self._patient("10000000002")
        self._history(low_patient, no_shows=0, completed=10)
        low_appt = self._appt(low_patient, offset_days=2, status="scheduled")

        # (c) Inert: 1 no_show + 2 completed = 3 terminal < 5 → no row
        inert_patient = self._patient("10000000003")
        self._history(inert_patient, no_shows=1, completed=2)
        inert_appt = self._appt(inert_patient, offset_days=2, status="scheduled")

        counts = NoShowService().evaluate_window(now=self.now)

        # (a) high band
        high_risk = NoShowRisk.objects.get(appointment=high_appt)
        assert high_risk.band == NoShowRisk.Band.HIGH, (
            f"Expected high band for frequent no-show patient, got {high_risk.band!r}; "
            f"score={high_risk.score}"
        )

        # (b) low band
        low_risk = NoShowRisk.objects.get(appointment=low_appt)
        assert low_risk.band == NoShowRisk.Band.LOW, (
            f"Expected low band for perfect-attendance patient, got {low_risk.band!r}; "
            f"score={low_risk.score}"
        )

        # (c) inert: no row created
        assert not NoShowRisk.objects.filter(appointment=inert_appt).exists(), (
            "Inert patient (< 5 terminal) must not create a NoShowRisk row"
        )

        # Sanity-check service counters: 2 scored, 1 inert
        assert counts["scored"] == 2, f"Expected 2 scored, got {counts}"
        assert counts["inert"] == 1, f"Expected 1 inert, got {counts}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. grade_predictions writes AuditLog flywheel entry
# ─────────────────────────────────────────────────────────────────────────────


class TestGradeWritesFlywheelAuditLog(_Base):
    """grade_predictions stores outcome=true_positive AND an AuditLog entry."""

    def test_grade_writes_flywheel_auditlog(self):
        # Seed a high-risk open prediction whose appointment is now past-due and
        # terminated as no_show.
        patient = self._patient("20000000001")
        # Past appointment: offset_days=-1 puts start_time before self.now.
        appt = self._appt(patient, offset_days=-1, status="no_show")
        risk = NoShowRisk.objects.create(
            appointment=appt,
            score="0.6000",
            band=NoShowRisk.Band.HIGH,
            engine_version="noshow-n1",
        )

        # Snapshot audit count before grading.
        audit_count_before = AuditLog.objects.count()

        svc = NoShowService(requesting_user=self.user)
        svc.grade_predictions(now=self.now)

        # The risk must now be graded as true_positive.
        risk.refresh_from_db()
        assert risk.outcome == NoShowRisk.Outcome.TRUE_POSITIVE, (
            f"Expected true_positive, got {risk.outcome!r}"
        )
        assert risk.graded_at is not None, "graded_at must be set after grading"

        # Exactly one new AuditLog entry must have been written.
        new_entries = AuditLog.objects.filter(action="no_show_prediction_graded")
        assert new_entries.count() == audit_count_before + 1, (
            f"Expected 1 new AuditLog(action='no_show_prediction_graded'), "
            f"got {new_entries.count() - audit_count_before}"
        )

        entry = new_entries.latest("id")
        assert entry.resource_type == "no_show_risk"
        assert entry.resource_id == str(risk.id)

        # new_data must include score and outcome.
        nd = entry.new_data
        assert "score" in nd, f"score missing from AuditLog.new_data: {nd}"
        assert "outcome" in nd, f"outcome missing from AuditLog.new_data: {nd}"
        assert nd["outcome"] == NoShowRisk.Outcome.TRUE_POSITIVE.value, (
            f"AuditLog outcome mismatch: {nd['outcome']!r}"
        )
        assert nd["band"] == NoShowRisk.Band.HIGH.value, (
            f"AuditLog band mismatch: {nd['band']!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Flag OFF → evaluate_window is a no-op
# ─────────────────────────────────────────────────────────────────────────────


class TestFlagOffEvaluateIsNoop(_Base):
    """When the feature flag is disabled, evaluate_window must create zero rows."""

    def test_flag_off_evaluate_is_noop(self):
        self._disable_flag()

        # Give the patient enough history to score (would produce a row if flag were on).
        patient = self._patient("30000000001")
        self._history(patient, no_shows=6, completed=4)
        self._appt(patient, offset_days=2, status="scheduled")

        counts = NoShowService().evaluate_window(now=self.now)

        assert NoShowRisk.objects.count() == 0, (
            "evaluate_window must create zero NoShowRisk rows when flag is OFF"
        )
        assert counts == {"scored": 0, "inert": 0}, (
            f"Expected zero counts when flag is OFF, got {counts}"
        )
