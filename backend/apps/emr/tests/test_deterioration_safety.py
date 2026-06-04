"""Orchestrator + signal tests for the clinical-deterioration wedge (PR D2).

The NEWS2 scoring is PURE and tested exhaustively in test_news2_engine. Here we
test the SERVICE side-effects (DeteriorationService) and the post_save signal
wiring:
  * flag-OFF no-op (regression guard — no alert, no audit);
  * inert when vitals incomplete (engine None) or band is plain low;
  * severity mapping (high → escalation, else advise);
  * de-dup (LOCKED): escalate the open alert only if score rose; no new alert
    while one is open; a NEW alert after the previous is acknowledged;
  * flywheel AuditLog with the labeled-example fields;
  * SpO2 Scale 2 honoured from Patient.use_spo2_scale_2;
  * the post_save → on_commit → evaluate signal actually fires.

Run: python manage.py test apps.emr.tests.test_deterioration_safety
"""

from decimal import Decimal

from apps.core.models import AuditLog, FeatureFlag, User
from apps.emr.models import (
    DeteriorationAlert,
    Encounter,
    Patient,
    Professional,
    VitalSigns,
)
from apps.emr.services.deterioration import DeteriorationService
from apps.test_utils import TenantTestCase

# Vital-sign sets keyed to known NEWS2 outcomes (Scale 1). See test_news2_engine.
NORMAL = {  # score 0 → band low
    "respiratory_rate": 16,
    "oxygen_saturation": 98,
    "on_supplemental_oxygen": False,
    "blood_pressure_systolic": 120,
    "heart_rate": 70,
    "temperature_celsius": Decimal("36.8"),
    "consciousness": "A",
}


def _vitals_kwargs(**overrides):
    return {**NORMAL, **overrides}


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self.set_flag(True)
        self.user = User.objects.create_user(
            email="enf@test.com", full_name="Enfermeira", password="Str0ng!Pass#2024"
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Deterioração",
            birth_date="1980-01-01",
            gender="M",
            cpf="11122233344",
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="COREN", council_number="9", council_state="SP"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)

    def set_flag(self, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="deterioration_safety",
            defaults={"is_enabled": enabled},
        )

    def _vitals(self, **overrides):
        return VitalSigns.objects.create(encounter=self.encounter, **_vitals_kwargs(**overrides))

    def _evaluate(self, vs):
        return DeteriorationService(requesting_user=self.user).evaluate(vs)

    def _open_alerts(self):
        return DeteriorationAlert.objects.filter(
            encounter=self.encounter, status=DeteriorationAlert.Status.OPEN
        )


class TestInertPaths(_Base):
    def test_flag_off_is_noop(self):
        self.set_flag(False)
        # A clearly-high vitals set; with the flag off nothing must be written.
        vs = self._vitals(respiratory_rate=28, heart_rate=125, temperature_celsius=Decimal("39.5"))
        assert self._evaluate(vs) is None
        assert DeteriorationAlert.objects.count() == 0
        assert AuditLog.objects.filter(resource_type="deterioration_alert").count() == 0

    def test_incomplete_vitals_is_noop(self):
        # Respiratory rate missing → engine inert (None) → no alert (no imputation).
        vs = self._vitals(respiratory_rate=None, heart_rate=125)
        assert self._evaluate(vs) is None
        assert DeteriorationAlert.objects.count() == 0

    def test_low_band_is_noop(self):
        vs = self._vitals()  # all normal → score 0 → low
        assert self._evaluate(vs) is None
        assert DeteriorationAlert.objects.count() == 0


class TestSeverityAndBands(_Base):
    def test_low_medium_single_param_three_raises_advise(self):
        # RR 26 alone → 3 points, single-param red score → low_medium.
        vs = self._vitals(respiratory_rate=26)
        alert = self._evaluate(vs)
        assert alert is not None
        assert alert.band == DeteriorationAlert.Band.LOW_MEDIUM
        assert alert.severity == DeteriorationAlert.Severity.ADVISE
        assert alert.status == DeteriorationAlert.Status.OPEN
        assert alert.score == 3
        assert alert.any_param_three is True
        assert alert.source == DeteriorationAlert.Source.ENGINE

    def test_medium_raises_advise(self):
        # RR 22 (2) + HR 125 (2) + SpO2 94 (1) = 5 → medium, no single 3.
        vs = self._vitals(respiratory_rate=22, heart_rate=125, oxygen_saturation=94)
        alert = self._evaluate(vs)
        assert alert.band == DeteriorationAlert.Band.MEDIUM
        assert alert.severity == DeteriorationAlert.Severity.ADVISE
        assert alert.score == 5
        assert alert.any_param_three is False

    def test_high_raises_escalation(self):
        # RR 28 (3) + HR 125 (2) + temp 39.5 (2) = 7 → high.
        vs = self._vitals(respiratory_rate=28, heart_rate=125, temperature_celsius=Decimal("39.5"))
        alert = self._evaluate(vs)
        assert alert.band == DeteriorationAlert.Band.HIGH
        assert alert.severity == DeteriorationAlert.Severity.ESCALATION
        assert alert.score == 7


class TestDedup(_Base):
    def test_escalates_open_alert_when_score_rises(self):
        first = self._evaluate(
            self._vitals(respiratory_rate=22, heart_rate=125, oxygen_saturation=94)
        )  # 5, medium
        assert first.score == 5
        # Higher reading: RR 28 (3) + HR 125 (2) + SpO2 90 (3) = 8 → high.
        second_vs = self._vitals(respiratory_rate=28, heart_rate=125, oxygen_saturation=90)
        second = self._evaluate(second_vs)
        # Same alert row, escalated in place.
        assert second.id == first.id
        assert second.score == 8
        assert second.band == DeteriorationAlert.Band.HIGH
        assert second.severity == DeteriorationAlert.Severity.ESCALATION
        assert second.vital_signs_id == second_vs.id
        assert DeteriorationAlert.objects.filter(encounter=self.encounter).count() == 1
        # One audit per side-effect (raised + escalated).
        assert AuditLog.objects.filter(resource_type="deterioration_alert").count() == 2

    def test_does_not_downgrade_or_spam_open_alert(self):
        high = self._evaluate(
            self._vitals(respiratory_rate=28, heart_rate=125, oxygen_saturation=90)
        )  # 8
        assert high.score == 8
        # Lower but still-flagged reading (medium, 5) must NOT touch the open alert.
        lower = self._evaluate(
            self._vitals(respiratory_rate=22, heart_rate=125, oxygen_saturation=94)
        )
        assert lower.id == high.id
        assert lower.score == 8  # unchanged
        assert DeteriorationAlert.objects.filter(encounter=self.encounter).count() == 1
        assert AuditLog.objects.filter(resource_type="deterioration_alert").count() == 1

    def test_new_alert_after_acknowledge(self):
        first = self._evaluate(self._vitals(respiratory_rate=26))  # low_medium
        first.acknowledge(self.user, note="visto")
        assert self._open_alerts().count() == 0
        # A fresh deterioration after ack creates a NEW open alert (history kept).
        second = self._evaluate(
            self._vitals(respiratory_rate=28, heart_rate=125, temperature_celsius=Decimal("39.5"))
        )
        assert second.id != first.id
        assert second.status == DeteriorationAlert.Status.OPEN
        assert DeteriorationAlert.objects.filter(encounter=self.encounter).count() == 2
        assert self._open_alerts().count() == 1


class TestFlywheelAudit(_Base):
    def test_audit_carries_labeled_example(self):
        vs = self._vitals(respiratory_rate=28, heart_rate=125, temperature_celsius=Decimal("39.5"))
        alert = self._evaluate(vs)
        log = AuditLog.objects.get(resource_type="deterioration_alert")
        assert log.action == "deterioration_alert_raised"
        assert log.resource_id == str(alert.id)
        assert log.new_data["score"] == 7
        assert log.new_data["band"] == "high"
        assert log.new_data["severity"] == "escalation"
        assert "breakdown" in log.new_data
        assert log.new_data["correlation_id"]


class TestSpO2Scale2(_Base):
    def test_scale_2_recorded_and_applied(self):
        self.patient.use_spo2_scale_2 = True
        self.patient.save(update_fields=["use_spo2_scale_2"])
        # SpO2 92 on air: Scale 2 → 0 (would be 2 on Scale 1). Still alert via
        # other params: RR 28 (3) + HR 125 (2) = 5 → medium.
        vs = self._vitals(oxygen_saturation=92, respiratory_rate=28, heart_rate=125)
        alert = self._evaluate(vs)
        assert alert.spo2_scale == 2
        assert alert.breakdown["spo2"] == 0
        assert alert.score == 5
        assert alert.band == DeteriorationAlert.Band.MEDIUM


class TestSignalWiring(_Base):
    """The post_save → on_commit → evaluate wiring.

    Uses captureOnCommitCallbacks(execute=True) because the on_commit callback
    never runs inside the default transaction-wrapped test. Runs in the tenant
    context (via _Base/TenantTestCase) so connection.tenant + the flag resolve.
    """

    def test_saving_high_vitals_raises_alert_via_signal(self):
        with self.captureOnCommitCallbacks(execute=True):
            VitalSigns.objects.create(
                encounter=self.encounter,
                respiratory_rate=28,
                oxygen_saturation=90,
                on_supplemental_oxygen=True,
                blood_pressure_systolic=88,
                heart_rate=124,
                temperature_celsius=Decimal("39.4"),
                consciousness="V",
            )
        alert = DeteriorationAlert.objects.filter(encounter=self.encounter).first()
        assert alert is not None
        assert alert.band == DeteriorationAlert.Band.HIGH
        assert alert.severity == DeteriorationAlert.Severity.ESCALATION
