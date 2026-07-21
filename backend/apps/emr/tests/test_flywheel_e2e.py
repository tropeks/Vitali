"""End-to-end flywheel cycle tests for the no-show and deterioration wedges.

Sprint S30-05: proves the full alert → override → outcome → signal cycle for
the no-show (N-wedge) and deterioration (D-wedge) wedges. Each test walks the
happy-path end-to-end: flag on → alert created → acknowledge → verify override
preserved / new-alert-after-ack → drive outcome → grade → AuditLog.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from apps.core.models import AuditLog, FeatureFlag, User
from apps.emr.models import (
    Appointment,
    DeteriorationAlert,
    Encounter,
    NoShowRisk,
    Patient,
    Professional,
    VitalSigns,
)
from apps.emr.services.deterioration import DeteriorationService
from apps.emr.services.no_show import NoShowService
from apps.test_utils import TenantTestCase

# ─── No-show flywheel ─────────────────────────────────────────────────────────


class TestNoShowFlywheelFullCycle(TenantTestCase):
    """Full alert → override → outcome → signal cycle for the no-show wedge."""

    def setUp(self):
        self.tenant = self.__class__.tenant
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant,
            module_key="no_show_prediction",
            defaults={"is_enabled": True},
        )
        self.now = timezone.now()
        self.user = User.objects.create_user(
            email="ns_flywheel@test.com",
            full_name="Recepção Flywheel",
            password="Str0ng!Pass#2024",
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="999", council_state="SP"
        )
        self._slot = 0

    def _appt(self, patient, *, offset_days, status, **kw):
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

    def _patient(self, cpf):
        return Patient.objects.create(
            full_name=f"Paciente {cpf}", birth_date="1980-01-01", gender="M", cpf=cpf
        )

    def _history(self, patient, *, no_shows, completed):
        for _ in range(no_shows):
            self._appt(patient, offset_days=-30, status="no_show")
        for _ in range(completed):
            self._appt(patient, offset_days=-30, status="completed")

    def test_no_show_flywheel_full_cycle(self):
        """flag ON → evaluate_window → NoShowRisk(open) → acknowledge →
        re-evaluate doesn't reopen → set status=no_show → grade → true_positive
        + AuditLog(action='no_show_prediction_graded') with score + outcome.
        """
        # ── Step 1: create patient with actionable no-show history ──────────────
        patient = self._patient("55500000001")
        self._history(patient, no_shows=4, completed=4)  # 8 terminal, 50% raw → enough

        # ── Step 2: upcoming appointment ────────────────────────────────────────
        appt = self._appt(patient, offset_days=2, status="scheduled")

        # ── Step 3: evaluate_window creates NoShowRisk(open) ────────────────────
        svc = NoShowService()
        svc.evaluate_window(now=self.now)

        risk = NoShowRisk.objects.get(appointment=appt)
        assert risk.status == NoShowRisk.Status.OPEN
        assert risk.outcome == NoShowRisk.Outcome.PENDING
        assert risk.band in ("low", "medium", "high")

        # ── Step 4: acknowledge → override is persisted ──────────────────────────
        risk.acknowledge(self.user, note="liguei pro paciente; confirmou presença")
        risk.refresh_from_db()
        assert risk.status == NoShowRisk.Status.ACKNOWLEDGED
        assert risk.acknowledged_by == self.user

        band_before = risk.band

        # ── Step 5: re-evaluate → override preserved (stays ACKNOWLEDGED) ────────
        svc.evaluate_window(now=self.now)
        risk.refresh_from_db()
        assert (
            risk.status == NoShowRisk.Status.ACKNOWLEDGED
        ), "re-evaluate must NOT reopen an acknowledged risk"
        assert risk.band == band_before, "band must not change when history is unchanged"

        # ── Step 6: patient actually no-shows → move appointment to past ─────────
        # Make the appointment start in the past so grade_predictions picks it up
        Appointment.objects.filter(pk=appt.pk).update(
            start_time=self.now - datetime.timedelta(hours=2),
            end_time=self.now - datetime.timedelta(hours=1, minutes=30),
            status="no_show",
        )

        # ── Step 7: grade_predictions → true_positive (high band no-show) ────────
        # Force the risk to high band so outcome is true_positive, not false_negative
        NoShowRisk.objects.filter(pk=risk.pk).update(band="high")

        svc2 = NoShowService()
        counts = svc2.grade_predictions(now=self.now)

        risk.refresh_from_db()
        assert risk.outcome == NoShowRisk.Outcome.TRUE_POSITIVE
        assert risk.graded_at is not None
        assert counts.get(NoShowRisk.Outcome.TRUE_POSITIVE.value, 0) >= 1

        # ── Step 8: AuditLog carries score + outcome ─────────────────────────────
        log = AuditLog.objects.filter(
            action="no_show_prediction_graded", resource_id=str(risk.id)
        ).first()
        assert log is not None, "AuditLog must be written after grading"
        assert "score" in log.new_data
        assert log.new_data["outcome"] == NoShowRisk.Outcome.TRUE_POSITIVE.value


# ─── Deterioration flywheel ───────────────────────────────────────────────────


class TestDeteriorationFlywheelFullCycle(TenantTestCase):
    """Full alert → acknowledge → new alert cycle for the deterioration wedge."""

    def setUp(self):
        self.tenant = self.__class__.tenant
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant,
            module_key="deterioration_safety",
            defaults={"is_enabled": True},
        )
        self.user = User.objects.create_user(
            email="enf_flywheel@test.com",
            full_name="Enfermeira Flywheel",
            password="Str0ng!Pass#2024",
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Deterioração E2E",
            birth_date="1980-01-01",
            gender="M",
            cpf="55500000002",
        )
        self.prof = Professional.objects.create(
            user=self.user, council_type="COREN", council_number="7", council_state="SP"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)

    def _svc(self):
        return DeteriorationService(requesting_user=self.user)

    def _vitals(self, **kw):
        defaults = {
            "respiratory_rate": 16,
            "oxygen_saturation": 98,
            "on_supplemental_oxygen": False,
            "blood_pressure_systolic": 120,
            "heart_rate": 70,
            "temperature_celsius": Decimal("36.8"),
            "consciousness": "A",
        }
        defaults.update(kw)
        return VitalSigns.objects.create(encounter=self.encounter, **defaults)

    def test_deterioration_flywheel_full_cycle(self):
        """flag ON → high-NEWS2 vitals → DeteriorationAlert(open, escalation) +
        AuditLog(action='deterioration_alert_raised') → acknowledge → higher
        vitals → NEW DeteriorationAlert created (de-dup released after ack) +
        AuditLog chain.
        """
        # ── Step 1: record high-NEWS2 vitals (score 7 → HIGH → escalation) ────
        # RR 28 (3pts) + HR 125 (2pts) + temp 39.5 (2pts) = 7 → high
        vs1 = self._vitals(
            respiratory_rate=28,
            heart_rate=125,
            temperature_celsius=Decimal("39.5"),
        )
        alert1 = self._svc().evaluate(vs1)

        assert alert1 is not None
        assert alert1.status == DeteriorationAlert.Status.OPEN
        assert alert1.band == DeteriorationAlert.Band.HIGH
        assert alert1.severity == DeteriorationAlert.Severity.ESCALATION
        assert alert1.score == 7

        # ── Step 2: AuditLog for initial alert creation ──────────────────────
        log1 = AuditLog.objects.filter(
            action="deterioration_alert_raised",
            resource_id=str(alert1.id),
        ).first()
        assert log1 is not None, "AuditLog must be created when alert is raised"
        assert log1.new_data["score"] == 7
        assert log1.new_data["band"] == "high"
        assert log1.new_data["severity"] == "escalation"
        assert "breakdown" in log1.new_data
        assert log1.new_data["correlation_id"]

        # ── Step 3: acknowledge the alert ────────────────────────────────────
        alert1.acknowledge(self.user, note="médico notificado; aguardando avaliação")
        alert1.refresh_from_db()
        assert alert1.status == DeteriorationAlert.Status.ACKNOWLEDGED

        # Verify no open alerts remain
        open_alerts = DeteriorationAlert.objects.filter(
            encounter=self.encounter, status=DeteriorationAlert.Status.OPEN
        )
        assert open_alerts.count() == 0, "no open alerts after acknowledge"

        # ── Step 4: record higher vitals → NEW alert created (de-dup released) ─
        # RR 28 (3pts) + HR 125 (2pts) + SpO2 90 (3pts) = 8 → high
        vs2 = self._vitals(
            respiratory_rate=28,
            heart_rate=125,
            oxygen_saturation=90,
        )
        alert2 = self._svc().evaluate(vs2)

        assert alert2 is not None
        assert alert2.id != alert1.id, "a new alert must be created after ack"
        assert alert2.status == DeteriorationAlert.Status.OPEN
        assert alert2.band == DeteriorationAlert.Band.HIGH
        assert alert2.severity == DeteriorationAlert.Severity.ESCALATION
        assert alert2.score == 8

        # Two DeteriorationAlert rows, one open
        assert DeteriorationAlert.objects.filter(encounter=self.encounter).count() == 2
        assert (
            DeteriorationAlert.objects.filter(
                encounter=self.encounter, status=DeteriorationAlert.Status.OPEN
            ).count()
            == 1
        )

        # ── Step 5: AuditLog chain has both raises ───────────────────────────
        all_logs = AuditLog.objects.filter(
            action="deterioration_alert_raised",
        ).order_by("created_at")
        assert all_logs.count() >= 2, "two audit entries — one per raise"
        # The second log references the new alert
        log2 = AuditLog.objects.filter(
            action="deterioration_alert_raised",
            resource_id=str(alert2.id),
        ).first()
        assert log2 is not None
        assert log2.new_data["score"] == 8
