"""Tests for WedgeTelemetryView (S30-04).

Covers the per-wedge operational telemetry endpoint: the three wedges are
reported, alert/ack counts drive the override rate, the flywheel surfaces the
outcome distribution + graded-event count, queries are tenant-scoped, and the
endpoint requires authentication.
"""

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import GlosaSafetyAlert, InsuranceProvider, TISSGuide
from apps.core.models import AuditLog, FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import (
    AISafetyAlert,
    Appointment,
    DeteriorationAlert,
    Encounter,
    NoShowRisk,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
    VitalSigns,
)
from apps.pharmacy.models import ControlledAlert, Dispensation, Drug, StockAlert
from apps.test_utils import TenantTestCase

URL = "/api/v1/wedge-telemetry/"


class _Base(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self.now = timezone.now()
        self._slot = 0

        role = Role.objects.create(
            name="medico_wt",
            permissions=DEFAULT_ROLES["medico"] + ["reports.read"],
        )
        self.user = User.objects.create_user(email="wt@t.com", password="pw", role=role)
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="9", council_state="SP"
        )

    def _set_flag(self, module_key, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=module_key,
            defaults={"is_enabled": enabled},
        )

    def _client(self, user=None):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user or self.user)
        return c

    # ── factories ─────────────────────────────────────────────────────────────
    def _no_show(self, *, score="0.6000", band="high", status="open", outcome="pending"):
        self._slot += 1
        patient = Patient.objects.create(
            full_name=f"Paciente {self._slot}",
            birth_date="1980-01-01",
            gender="F",
            cpf=f"5550000{self._slot:04d}",
        )
        start = self.now + datetime.timedelta(days=1, hours=self._slot)
        appt = Appointment.objects.create(
            patient=patient,
            professional=self.prof,
            start_time=start,
            end_time=start + datetime.timedelta(minutes=30),
            status="scheduled",
        )
        return NoShowRisk.objects.create(
            appointment=appt,
            score=score,
            band=band,
            status=status,
            outcome=outcome,
            suggested_action="confirm_active",
            engine_version="noshow-n1",
        )

    def _stockout(self, *, status="open"):
        self._slot += 1
        drug = Drug.objects.create(name=f"Dipirona {self._slot}", lead_time_days=10)
        return StockAlert.objects.create(
            drug=drug,
            kind=StockAlert.Kind.STOCKOUT_RISK,
            severity=StockAlert.Severity.ADVISE,
            status=status,
            predicted_date=self.now.date() + datetime.timedelta(days=5),
            message="risco de ruptura",
        )

    def _deterioration(self, *, status="open"):
        self._slot += 1
        patient = Patient.objects.create(
            full_name=f"Paciente D {self._slot}",
            birth_date="1980-01-01",
            gender="M",
            cpf=f"4440000{self._slot:04d}",
        )
        encounter = Encounter.objects.create(patient=patient, professional=self.prof)
        vs = VitalSigns.objects.create(
            encounter=encounter,
            respiratory_rate=28,
            oxygen_saturation=90,
            on_supplemental_oxygen=True,
            blood_pressure_systolic=100,
            heart_rate=120,
            temperature_celsius=Decimal("39.2"),
            consciousness="A",
        )
        return DeteriorationAlert.objects.create(
            encounter=encounter,
            vital_signs=vs,
            score=7,
            band="high",
            breakdown={"respiratory_rate": 3},
            any_param_three=True,
            spo2_scale=1,
            severity="escalation",
            status=status,
            engine_version="news2-rcp-2017-v1",
            message="NEWS2 7",
        )

    def _ai_safety_alert(self, *, alert_type, status="flagged"):
        self._slot += 1
        patient = Patient.objects.create(
            full_name=f"Safety Patient {self._slot}",
            birth_date="1985-01-01",
            gender="F",
            cpf=f"7770000{self._slot:04d}",
        )
        enc = Encounter.objects.create(patient=patient, professional=self.prof)
        rx = Prescription.objects.create(encounter=enc, patient=patient, prescriber=self.prof)
        drug = Drug.objects.create(name=f"Drug Safety {self._slot}")
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=1, unit_of_measure="un"
        )
        return AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type=alert_type,
            source="engine",
            severity="caution",
            message=f"{alert_type} alert",
            status=status,
        )

    def _glosa_safety_alert(self, *, status="flagged"):
        self._slot += 1
        patient = Patient.objects.create(
            full_name=f"Glosa Patient {self._slot}",
            birth_date="1985-01-01",
            gender="M",
            cpf=f"8880000{self._slot:04d}",
        )
        enc = Encounter.objects.create(patient=patient, professional=self.prof)
        provider = InsuranceProvider.objects.create(
            name=f"Provider {self._slot}", ans_code=f"{self._slot:06d}"
        )
        guide = TISSGuide.objects.create(
            guide_type="sadt",
            encounter=enc,
            patient=patient,
            provider=provider,
            insured_card_number=f"000000{self._slot:05d}",
            competency="2026-06",
            status="pending",
        )
        return GlosaSafetyAlert.objects.create(
            guide=guide,
            check_code="incomplete",
            severity="advise",
            source="engine",
            message="glosa alert",
            status=status,
        )

    def _controlled_safety_alert(self, *, status="open", outcome="pending"):
        self._slot += 1
        patient = Patient.objects.create(
            full_name=f"Controlled Patient {self._slot}",
            birth_date="1985-01-01",
            gender="M",
            cpf=f"9990000{self._slot:04d}",
        )
        drug = Drug.objects.create(name=f"Drug Controlled {self._slot}")
        enc = Encounter.objects.create(patient=patient, professional=self.prof)
        rx = Prescription.objects.create(encounter=enc, patient=patient, prescriber=self.prof)
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=1, unit_of_measure="un"
        )
        disp = Dispensation.objects.create(
            prescription=rx,
            prescription_item=item,
            patient=patient,
            dispensed_by=self.user,
        )
        return ControlledAlert.objects.create(
            dispensation=disp,
            patient=patient,
            drug=drug,
            signal_kind="refill_too_soon",
            detail={},
            status=status,
            outcome=outcome,
            engine_version="controlled-c1",
        )


class TestWedgeTelemetry(_Base):
    def test_returns_seven_wedges(self):
        self._set_flag("no_show_prediction", True)
        self._set_flag("stockout_safety", True)
        self._no_show()
        self._stockout()
        self._deterioration()

        body = self._client().get(URL).json()
        keys = [w["key"] for w in body["wedges"]]
        assert keys == [
            "no_show_prediction",
            "stockout_safety",
            "deterioration_safety",
            "dose_safety",
            "allergy_safety",
            "glosa_safety",
            "controlled_safety",
        ]
        by_key = {w["key"]: w for w in body["wedges"]}
        assert by_key["no_show_prediction"]["alert_count"] == 1
        assert by_key["stockout_safety"]["alert_count"] == 1
        assert by_key["deterioration_safety"]["alert_count"] == 1
        # Wave-2 wedges: no alerts seeded above — count must be 0.
        for wkey in ("dose_safety", "allergy_safety", "glosa_safety", "controlled_safety"):
            assert by_key[wkey]["alert_count"] == 0
        # Flag state is reflected per wedge.
        assert by_key["no_show_prediction"]["enabled"] is True
        assert by_key["deterioration_safety"]["enabled"] is False
        # Wedges are deterministic — no model/latency.
        for w in body["wedges"]:
            assert w["engine"] == "deterministic"

    def test_alert_count_and_override_rate(self):
        # 4 NoShowRisk alerts, 2 acknowledged → override_rate = 0.5
        self._no_show(status="open")
        self._no_show(status="open")
        self._no_show(status="acknowledged")
        self._no_show(status="acknowledged")

        body = self._client().get(URL).json()
        ns = next(w for w in body["wedges"] if w["key"] == "no_show_prediction")
        assert ns["alert_count"] == 4
        assert ns["acknowledged_count"] == 2
        assert ns["override_rate"] == 0.5

    def test_override_rate_null_when_no_alerts(self):
        body = self._client().get(URL).json()
        ns = next(w for w in body["wedges"] if w["key"] == "no_show_prediction")
        assert ns["alert_count"] == 0
        assert ns["override_rate"] is None

    def test_flywheel_outcome_counts(self):
        self._no_show(outcome="true_positive")
        self._no_show(outcome="false_positive")
        self._no_show(outcome="false_positive")

        body = self._client().get(URL).json()
        ns = next(w for w in body["wedges"] if w["key"] == "no_show_prediction")
        counts = ns["flywheel"]["outcome_counts"]
        assert counts == {"true_positive": 1, "false_positive": 2}

    def test_deterioration_outcome_counts_null(self):
        # DeteriorationAlert has no outcome field — must not be fabricated.
        self._deterioration()
        body = self._client().get(URL).json()
        det = next(w for w in body["wedges"] if w["key"] == "deterioration_safety")
        assert det["flywheel"]["outcome_counts"] is None

    def test_flywheel_graded_count(self):
        AuditLog.objects.create(
            action="no_show_prediction_graded", resource_type="no_show_risk", resource_id="a"
        )
        AuditLog.objects.create(
            action="no_show_prediction_graded", resource_type="no_show_risk", resource_id="b"
        )
        # Unrelated action — must not be counted.
        AuditLog.objects.create(action="login", resource_type="user", resource_id="1")

        body = self._client().get(URL).json()
        ns = next(w for w in body["wedges"] if w["key"] == "no_show_prediction")
        assert ns["flywheel"]["graded_count"] == 2

    def test_days_window_excludes_old_alerts(self):
        old = self._no_show()
        NoShowRisk.objects.filter(pk=old.pk).update(
            created_at=self.now - datetime.timedelta(days=90)
        )
        self._no_show()  # in-window

        body = self._client().get(URL, {"days": 30}).json()
        ns = next(w for w in body["wedges"] if w["key"] == "no_show_prediction")
        assert ns["alert_count"] == 1

    def test_tenant_isolated(self):
        # Seed in this tenant; the query is schema-scoped (django-tenants) and the
        # AuditLog flywheel is read through for_current_tenant. A row stamped for a
        # different schema must NOT be counted here.
        self._no_show()
        AuditLog.objects.create(
            action="no_show_prediction_graded",
            resource_type="no_show_risk",
            resource_id="mine",
        )
        AuditLog.objects.create(
            action="no_show_prediction_graded",
            resource_type="no_show_risk",
            resource_id="other",
            schema_name="other_clinic",
        )

        body = self._client().get(URL).json()
        ns = next(w for w in body["wedges"] if w["key"] == "no_show_prediction")
        assert ns["alert_count"] == 1
        # Only the current-tenant graded row counts (other_clinic excluded).
        assert ns["flywheel"]["graded_count"] == 1

    def test_requires_authentication(self):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = c.get(URL)
        assert resp.status_code in (401, 403)

    def test_requires_reports_read_permission(self):
        # A user whose role lacks reports.read must receive 403.
        restricted_role = Role.objects.create(
            name="medico_no_reports",
            permissions=[p for p in DEFAULT_ROLES["medico"] if p != "reports.read"],
        )
        restricted_user = User.objects.create_user(
            email="restricted@t.com", password="pw", role=restricted_role
        )
        resp = self._client(user=restricted_user).get(URL)
        assert resp.status_code == 403


class TestWaveTwoWedges(_Base):
    """S31-05 — Wave-2 wedges appear in the telemetry endpoint."""

    def test_dose_safety_alert_counted(self):
        """engine-source dose AISafetyAlert increments the dose_safety wedge count."""
        self._ai_safety_alert(alert_type="dose")
        body = self._client().get(URL).json()
        dose = next(w for w in body["wedges"] if w["key"] == "dose_safety")
        assert dose["alert_count"] == 1
        assert dose["acknowledged_count"] == 0
        # override_rate = 0 acks / 1 alert = 0.0
        assert dose["override_rate"] == 0.0

    def test_allergy_safety_llm_rows_excluded(self):
        """allergy wedge counts only source=engine rows; LLM rows are ignored."""
        self._ai_safety_alert(alert_type="allergy")
        # Create an LLM-source row for the same alert_type — must NOT be counted.
        slot_patient = Patient.objects.create(
            full_name="LLM Patient",
            birth_date="1985-01-01",
            gender="F",
            cpf="66600000099",
        )
        enc = Encounter.objects.create(patient=slot_patient, professional=self.prof)
        rx = Prescription.objects.create(encounter=enc, patient=slot_patient, prescriber=self.prof)
        drug = Drug.objects.create(name="Drug LLM")
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=1, unit_of_measure="un"
        )
        AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type="allergy",
            source="llm",
            severity="caution",
            message="llm allergy explanation",
        )

        body = self._client().get(URL).json()
        allergy = next(w for w in body["wedges"] if w["key"] == "allergy_safety")
        assert allergy["alert_count"] == 1, "LLM row must not be counted in allergy_safety"

    def test_glosa_safety_counted_no_outcome(self):
        """GlosaSafetyAlert increments glosa_safety; outcome_counts is null (was_denied ≠ TextChoices)."""
        self._glosa_safety_alert()
        body = self._client().get(URL).json()
        glosa = next(w for w in body["wedges"] if w["key"] == "glosa_safety")
        assert glosa["alert_count"] == 1
        assert glosa["flywheel"]["outcome_counts"] is None

    def test_controlled_safety_outcome_counts(self):
        """ControlledAlert has an outcome field; outcome_counts reflects the distribution."""
        self._controlled_safety_alert(outcome="true_positive")
        self._controlled_safety_alert(outcome="false_positive")
        self._controlled_safety_alert(outcome="false_positive")
        body = self._client().get(URL).json()
        ctrl = next(w for w in body["wedges"] if w["key"] == "controlled_safety")
        assert ctrl["alert_count"] == 3
        counts = ctrl["flywheel"]["outcome_counts"]
        assert counts["true_positive"] == 1
        assert counts["false_positive"] == 2

    def test_wave_two_override_rate(self):
        """Acknowledged Wave-2 alerts drive the override_rate correctly."""
        self._ai_safety_alert(alert_type="dose", status="flagged")
        self._ai_safety_alert(alert_type="dose", status="acknowledged")
        body = self._client().get(URL).json()
        dose = next(w for w in body["wedges"] if w["key"] == "dose_safety")
        assert dose["alert_count"] == 2
        assert dose["acknowledged_count"] == 1
        assert dose["override_rate"] == 0.5
