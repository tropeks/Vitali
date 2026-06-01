"""Integration tests for dose-safety soft-stop enforcement (wedge PR B).

Covers both gates (sign + dispense), the feature-flag-OFF no-op, the
acknowledge-with-reason override, the engine-vs-llm row independence, the
ENGINE_ERROR advisory path, the flywheel AuditLog, and the concurrent-lock path.

═══════════════════════════════════════════════════════════════════════════════
ILLUSTRATIVE TEST NUMBERS — NOT CLINICAL TRUTH (see test_dose_checker.py header).
═══════════════════════════════════════════════════════════════════════════════
"""

from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import (
    AISafetyAlert,
    Encounter,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
    VitalSigns,
)
from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary, StockItem, StockMovement
from apps.test_utils import TenantTestCase


def make_perkg_drug():
    """ILLUSTRATIVE per_kg formulary: band [0.5,1.0] mg/kg, abs cap 50mg. NOT clinical."""
    drug = Drug.objects.create(name="FAKE-Enf-PerKg", generic_name="fake_enf_perkg")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="IV",
        is_injectable=True,
        is_high_alert=True,
        active=True,
    )
    DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=Decimal("0.5000"),
        max_per_kg=Decimal("1.0000"),
        absolute_max_dose=Decimal("50.0000"),
        active=True,
    )
    return drug


class _EnforceBase(TenantTestCase):
    def setUp(self):
        self.tenant = self.__class__.tenant
        self._set_flag(True)

        role_md = Role.objects.create(name="medico_e", permissions=DEFAULT_ROLES["medico"])
        self.doctor = User.objects.create_user(email="dose_md@t.com", password="pw", role=role_md)
        role_ph = Role.objects.create(name="farma_e", permissions=DEFAULT_ROLES["farmaceutico"])
        self.pharmacist = User.objects.create_user(
            email="dose_ph@t.com", password="pw", role=role_ph
        )
        FeatureFlag.objects.update_or_create(
            tenant=self.tenant, module_key="pharmacy", defaults={"is_enabled": True}
        )

        self.patient = Patient.objects.create(
            full_name="Dose Patient",
            birth_date="1990-01-01",
            gender="M",
            cpf="55566677788",
        )
        self.prof = Professional.objects.create(
            user=self.doctor, council_type="CRM", council_number="42", council_state="SP"
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prof)
        # Fresh weight 10 kg so per-kg band = [5,10] mg.
        VitalSigns.objects.create(encounter=self.encounter, weight_kg=Decimal("10.00"))

    def _set_flag(self, enabled):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="dose_safety",
            defaults={"is_enabled": enabled},
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _make_rx(self, *, dose, unit="mg", route="IV", drug=None, signed=False):
        drug = drug or make_perkg_drug()
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prof
        )
        if signed:
            rx.sign(self.doctor)
        item = PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            quantity=Decimal("5"),
            unit_of_measure="un",
            dose_amount=dose,
            dose_unit=unit,
            route=route,
            frequency_per_day=1,
        )
        return rx, item

    def _sign(self, rx):
        return self._client(self.doctor).post(f"/api/v1/prescriptions/{rx.id}/sign/")


class TestSignGate(_EnforceBase):
    def test_sign_blocks_409_on_out_of_range(self):
        rx, _item = self._make_rx(dose=Decimal("40"))  # band [5,10] → OUT_OF_RANGE
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "dose_safety_block")
        self.assertTrue(resp.data["alerts"])
        rx.refresh_from_db()
        self.assertFalse(rx.is_signed)

    def test_sign_succeeds_within_band(self):
        rx, _item = self._make_rx(dose=Decimal("7"))  # in band → SAFE
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)

    def test_sign_succeeds_after_acknowledge_with_reason(self):
        rx, _item = self._make_rx(dose=Decimal("40"))
        self.assertEqual(self._sign(rx).status_code, 409)

        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "contraindication")
        ack_url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"

        # Acknowledge with a valid reason → 200.
        ack = self._client(self.doctor).post(
            ack_url, {"reason": "Dose intencional conforme protocolo documentado"}
        )
        self.assertEqual(ack.status_code, 200)

        # Re-sign now succeeds (block predicate no longer matches the acked row).
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)

    def test_acknowledge_without_reason_rejected(self):
        rx, _item = self._make_rx(dose=Decimal("40"))
        self._sign(rx)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        ack_url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"
        ack = self._client(self.doctor).post(ack_url, {"reason": "curto"})
        self.assertEqual(ack.status_code, 400)
        # Still blocking.
        self.assertEqual(self._sign(rx).status_code, 409)

    def test_weight_gate_blocks_when_no_weight(self):
        # Patient with no VitalSigns weight → per_kg → WEIGHT_GATE (blocking).
        patient2 = Patient.objects.create(
            full_name="No Weight", birth_date="1990-01-01", gender="F", cpf="99988877766"
        )
        enc2 = Encounter.objects.create(patient=patient2, professional=self.prof)
        rx = Prescription.objects.create(encounter=enc2, patient=patient2, prescriber=self.prof)
        PrescriptionItem.objects.create(
            prescription=rx,
            drug=make_perkg_drug(),
            quantity=Decimal("5"),
            dose_amount=Decimal("7"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 409)


class TestFeatureFlagOff(_EnforceBase):
    def test_sign_unaffected_when_flag_off(self):
        self._set_flag(False)
        rx, _item = self._make_rx(dose=Decimal("40"))  # would be OUT_OF_RANGE if ON
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)
        # No engine alert written.
        self.assertFalse(
            AISafetyAlert.objects.filter(
                prescription_item__prescription=rx, source="engine"
            ).exists()
        )


class TestDispenseGate(_EnforceBase):
    def _make_lot(self, drug, qty):
        future = (timezone.now() + timezone.timedelta(days=90)).date()
        item = StockItem.objects.create(drug=drug, lot_number="L1", expiry_date=future)
        StockMovement(stock_item=item, movement_type="entry", quantity=qty).save()
        return item

    def test_dispense_reevaluates_and_blocks(self):
        """A dose edited to out-of-range AFTER signing must be caught at dispense."""
        drug = make_perkg_drug()
        self._make_lot(drug, Decimal("10"))
        rx, item = self._make_rx(dose=Decimal("7"), drug=drug, signed=True)
        # Edit dose post-sign to an out-of-range value.
        item.dose_amount = Decimal("40")
        item.save(update_fields=["dose_amount"])

        resp = self._client(self.pharmacist).post(
            "/api/v1/pharmacy/dispense/",
            {"prescription_item_id": str(item.id), "quantity": "1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "dose_safety_block")

    def test_dispense_succeeds_when_safe(self):
        drug = make_perkg_drug()
        self._make_lot(drug, Decimal("10"))
        rx, item = self._make_rx(dose=Decimal("7"), drug=drug, signed=True)
        resp = self._client(self.pharmacist).post(
            "/api/v1/pharmacy/dispense/",
            {"prescription_item_id": str(item.id), "quantity": "1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)


class TestEngineLlmIndependence(_EnforceBase):
    def test_engine_row_does_not_clobber_acked_llm_row(self):
        rx, item = self._make_rx(dose=Decimal("40"))
        # Pre-existing acknowledged LLM dose alert (e.g. from the explainer path).
        llm_alert = AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type="dose",
            source="llm",
            severity="contraindication",
            status="acknowledged",
            message="LLM explanation",
            override_reason="motivo previamente registrado",
            acknowledged_by=self.doctor,
            acknowledged_at=timezone.now(),
        )
        # Signing runs the engine, which upserts its OWN row keyed on source=engine.
        self.assertEqual(self._sign(rx).status_code, 409)

        llm_alert.refresh_from_db()
        # The llm row is untouched.
        self.assertEqual(llm_alert.status, "acknowledged")
        self.assertEqual(llm_alert.override_reason, "motivo previamente registrado")
        # And a separate engine row exists.
        self.assertTrue(
            AISafetyAlert.objects.filter(
                prescription_item=item, source="engine", alert_type="dose"
            ).exists()
        )


class TestAdvisoryPaths(_EnforceBase):
    def test_data_missing_is_advisory_not_block(self):
        # Unit mismatch (mcg vs rule mg) → DATA_MISSING → caution, NON-blocking.
        rx, _item = self._make_rx(dose=Decimal("7"), unit="mcg")
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")

    def test_engine_error_is_advisory_not_silent_pass(self):
        from unittest.mock import patch

        from apps.pharmacy.services.dose_checker import DoseVerdict, Verdict

        rx, _item = self._make_rx(dose=Decimal("7"))
        err = DoseVerdict(verdict=Verdict.ENGINE_ERROR, reason="boom")
        with patch("apps.pharmacy.services.dose_checker.DoseChecker.check", return_value=err):
            resp = self._sign(rx)
        # Advisory: allowed (200), but an alert row is written (not silent).
        self.assertEqual(resp.status_code, 200)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")


class TestFlywheelAudit(_EnforceBase):
    def test_audit_written_with_correlation_id_and_verdict(self):
        from apps.core.models import AuditLog

        rx, _item = self._make_rx(dose=Decimal("40"))
        self._sign(rx)
        audit = AuditLog.objects.filter(action="dose_alert_raised").order_by("-created_at").first()
        self.assertIsNotNone(audit)
        self.assertIn("correlation_id", audit.new_data)
        self.assertEqual(audit.new_data["verdict"], "OUT_OF_RANGE")
        self.assertEqual(audit.new_data["gate"], "sign")
        self.assertEqual(audit.new_data["expected_low"], "5.0000")
        self.assertEqual(audit.new_data["expected_high"], "10.0000")
        self.assertIsNotNone(audit.new_data["rule_id"])


class TestConcurrentSignLock(_EnforceBase):
    def test_sign_uses_select_for_update_lock(self):
        """The sign path must lock the prescription row before evaluating/signing.

        We assert select_for_update is invoked on Prescription during sign — the
        lock is what makes the re-check inside the txn safe against a concurrent
        acknowledge/edit.
        """
        from unittest.mock import patch

        rx, _item = self._make_rx(dose=Decimal("7"))
        real_sfu = Prescription.objects.select_for_update

        called = {"n": 0}

        def _spy(*args, **kwargs):
            called["n"] += 1
            return real_sfu(*args, **kwargs)

        with patch.object(Prescription.objects, "select_for_update", side_effect=_spy):
            resp = self._sign(rx)

        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(called["n"], 1)
