"""S30-03: Escalation routing tests — per-tenant EscalationConfig wired to NEWS2 alerts.

Tests:
  - escalation alert routes when config is active
  - advise alert does NOT route (below min_severity)
  - no config → silent no-op (no exception, alert still created)
  - routing failure never blocks vitals recording
  - inactive config does not route

The router is always fail-safe: any error is logged and swallowed. Vitals
recording (and DeteriorationAlert creation) must survive a routing crash.

Run: docker compose exec -T django pytest apps/emr/tests/test_escalation_routing.py -v
"""

from decimal import Decimal
from unittest.mock import patch

from apps.core.models import AuditLog, FeatureFlag, User
from apps.emr.models import DeteriorationAlert, EscalationConfig, Patient, Professional
from apps.emr.services.deterioration import DeteriorationService
from apps.test_utils import TenantTestCase


def _enable_flag(tenant):
    FeatureFlag.objects.update_or_create(
        tenant=tenant,
        module_key="deterioration_safety",
        defaults={"is_enabled": True},
    )


class EscalationRoutingTests(TenantTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="nurse@test.com",
            full_name="Enfermeira Test",
            password="Str0ng!Pass#2024",
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="COREN", council_number="99", council_state="SP"
        )

    def _make_patient(self):
        return Patient.objects.create(
            full_name="Paciente Teste",
            birth_date="1970-01-01",
            cpf="",
        )

    def _make_encounter(self, patient):
        from apps.emr.models import Encounter
        return Encounter.objects.create(
            patient=patient,
            professional=self.prof,
        )

    def _make_vitals(self, encounter, *, high=True):
        """High score → NEWS2 high band (escalation); low score → advise."""
        from apps.emr.models import VitalSigns
        if high:
            # Respiratory rate 25 (3pts), heart rate 125 (3pts), temp 39.5 (1pt) = 7 → high
            return VitalSigns.objects.create(
                encounter=encounter,
                respiratory_rate=Decimal("25"),
                oxygen_saturation=Decimal("95"),
                on_supplemental_oxygen=False,
                blood_pressure_systolic=Decimal("111"),
                heart_rate=Decimal("125"),
                temperature_celsius=Decimal("39.5"),
                consciousness="A",
            )
        else:
            # Mild: respiratory rate 20 (1pt), everything else normal → score ~1, low band
            return VitalSigns.objects.create(
                encounter=encounter,
                respiratory_rate=Decimal("20"),
                oxygen_saturation=Decimal("97"),
                on_supplemental_oxygen=False,
                blood_pressure_systolic=Decimal("120"),
                heart_rate=Decimal("80"),
                temperature_celsius=Decimal("37.0"),
                consciousness="A",
            )

    def test_escalation_alert_routes_when_config_active(self):
        """Escalation-severity alert + active EscalationConfig → routing audited."""
        _enable_flag(self.tenant)
        EscalationConfig.objects.create(
            is_active=True,
            notify_emails=["duty@hospital.com"],
        )

        patient = self._make_patient()
        enc = self._make_encounter(patient)
        vs = self._make_vitals(enc, high=True)

        svc = DeteriorationService()
        alert = svc.evaluate(vs)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, DeteriorationAlert.Severity.ESCALATION)

        routed = AuditLog.objects.filter(action="deterioration_escalation_routed").first()
        self.assertIsNotNone(routed, "Escalation routing must write an AuditLog")
        self.assertIn("alert_id", routed.new_data)

    def test_advise_alert_does_not_route(self):
        """Advise-severity alert (medium band) → no routing (below min_severity=escalation)."""
        _enable_flag(self.tenant)
        EscalationConfig.objects.create(is_active=True, notify_emails=["duty@hospital.com"])

        patient = self._make_patient()
        enc = self._make_encounter(patient)
        # Score that yields medium band (advise, no single param = 3):
        # RR=21 → 2pts (21-24); SBP=100 → 2pts (91-100); HR=100 → 1pt (91-110) = 5 → MEDIUM
        from apps.emr.models import VitalSigns  # noqa: PLC0415
        vs = VitalSigns.objects.create(
            encounter=enc,
            respiratory_rate=Decimal("21"),
            oxygen_saturation=Decimal("97"),
            on_supplemental_oxygen=False,
            blood_pressure_systolic=Decimal("100"),
            heart_rate=Decimal("100"),
            temperature_celsius=Decimal("37.0"),
            consciousness="A",
        )

        svc = DeteriorationService()
        alert = svc.evaluate(vs)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, DeteriorationAlert.Severity.ADVISE)
        self.assertEqual(
            AuditLog.objects.filter(action="deterioration_escalation_routed").count(),
            0,
            "Advise-only alerts must not trigger escalation routing",
        )

    def test_no_config_is_silent_noop(self):
        """No EscalationConfig → alert still created, no routing, no exception."""
        _enable_flag(self.tenant)
        # No EscalationConfig row — should be a silent no-op

        patient = self._make_patient()
        enc = self._make_encounter(patient)
        vs = self._make_vitals(enc, high=True)

        svc = DeteriorationService()
        alert = svc.evaluate(vs)

        self.assertIsNotNone(alert, "DeteriorationAlert must be created even with no config")
        self.assertEqual(
            AuditLog.objects.filter(action="deterioration_escalation_routed").count(),
            0,
        )

    def test_routing_failure_never_blocks_vitals(self):
        """Router crash → VitalSigns + DeteriorationAlert preserved, error swallowed."""
        _enable_flag(self.tenant)
        EscalationConfig.objects.create(is_active=True, notify_emails=["duty@hospital.com"])

        patient = self._make_patient()
        enc = self._make_encounter(patient)
        vs = self._make_vitals(enc, high=True)

        with patch(
            "apps.emr.services.escalation.EscalationRouter._notify",
            side_effect=RuntimeError("network unreachable"),
        ):
            svc = DeteriorationService()
            # Must not raise
            alert = svc.evaluate(vs)

        self.assertIsNotNone(alert, "Alert must still be created on routing failure")
        from apps.emr.models import VitalSigns
        self.assertTrue(VitalSigns.objects.filter(pk=vs.pk).exists())

    def test_inactive_config_does_not_route(self):
        """is_active=False config → alert created, no routing."""
        _enable_flag(self.tenant)
        EscalationConfig.objects.create(is_active=False, notify_emails=["duty@hospital.com"])

        patient = self._make_patient()
        enc = self._make_encounter(patient)
        vs = self._make_vitals(enc, high=True)

        svc = DeteriorationService()
        alert = svc.evaluate(vs)

        self.assertIsNotNone(alert)
        self.assertEqual(
            AuditLog.objects.filter(action="deterioration_escalation_routed").count(),
            0,
        )
