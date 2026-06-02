"""Integration tests for dose-safety soft-stop enforcement (wedge PR B).

Covers both gates (sign + dispense), the feature-flag-OFF no-op, the
acknowledge-with-reason override, the engine-vs-llm row independence, the
ENGINE_ERROR advisory path, the flywheel AuditLog, and the concurrent-lock path.

═══════════════════════════════════════════════════════════════════════════════
ILLUSTRATIVE TEST NUMBERS — NOT CLINICAL TRUTH (see test_dose_checker.py header).
═══════════════════════════════════════════════════════════════════════════════
"""

from datetime import date
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


class TestBlockingKind(_EnforceBase):
    def test_out_of_range_payload_has_blocking_kind(self):
        rx, _item = self._make_rx(dose=Decimal("40"))  # band [5,10] → OUT_OF_RANGE
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.data["alerts"])
        self.assertEqual(resp.data["alerts"][0]["blocking_kind"], "out_of_range")

    def test_weight_gate_payload_has_blocking_kind(self):
        # Patient with no recorded weight → per_kg → WEIGHT_GATE (blocking).
        patient2 = Patient.objects.create(
            full_name="BK No Weight", birth_date=date(1990, 1, 1), gender="F", cpf="10101010101"
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
        self.assertTrue(resp.data["alerts"])
        self.assertEqual(resp.data["alerts"][0]["blocking_kind"], "weight_gate")


class TestWeightGateAckRefused(_EnforceBase):
    def test_weight_gate_ack_refused_409(self):
        """The authority refuses to acknowledge a weight-gate block — you cannot
        reason away a missing weight, you must record it."""
        patient2 = Patient.objects.create(
            full_name="WG Ack", birth_date=date(1990, 1, 1), gender="F", cpf="20202020202"
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
        self.assertEqual(self._sign(rx).status_code, 409)

        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        ack_url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"
        ack = self._client(self.doctor).post(
            ack_url, {"reason": "Tentando reconhecer sem registrar o peso"}
        )
        self.assertEqual(ack.status_code, 409)
        alert.refresh_from_db()
        # The alert is NOT acknowledged — the gate stays blocked.
        self.assertEqual(alert.status, "flagged")
        self.assertIsNone(alert.acknowledged_by)

    def test_normal_contraindication_still_acknowledges(self):
        """A normal (out-of-range) contraindication remains overridable."""
        rx, _item = self._make_rx(dose=Decimal("40"))  # OUT_OF_RANGE
        self.assertEqual(self._sign(rx).status_code, 409)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        ack_url = f"/api/v1/safety-alerts/{alert.id}/acknowledge/"
        ack = self._client(self.doctor).post(
            ack_url, {"reason": "Dose intencional conforme protocolo documentado"}
        )
        self.assertEqual(ack.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")


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

    def test_flag_off_releases_preexisting_blocking_alert(self):
        """A pre-existing flagged engine contraindication alert must NOT keep the
        gate locked once the flag is turned OFF — has_blocking returns False and
        sign() succeeds (no permanent 409 lock)."""
        from apps.emr.services.dose_safety import DoseCheckService

        rx, item = self._make_rx(dose=Decimal("40"))
        # Simulate a flagged blocking alert left over from when the flag was ON.
        AISafetyAlert.objects.create(
            prescription_item=item,
            alert_type="dose",
            source="engine",
            severity="contraindication",
            status="flagged",
            message="Dose 40 mg fora do intervalo esperado 5–10 mg.",
        )
        # Flag ON: gate is blocking.
        self.assertTrue(DoseCheckService.has_blocking_dose_alert(rx))

        # Turn the flag OFF.
        self._set_flag(False)
        # The self-guard releases the gate even though the flagged row still exists.
        self.assertFalse(DoseCheckService.has_blocking_dose_alert(rx))

        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)


class TestUnitMismatchBlocks(_EnforceBase):
    def test_unit_mismatch_blocks_sign_409(self):
        """A structured dose with a mismatched unit (mcg vs rule mg) must BLOCK —
        a silent 1000x overdose can never sail through the sign gate."""
        rx, _item = self._make_rx(dose=Decimal("7"), unit="mcg")
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "dose_safety_block")
        self.assertTrue(resp.data["alerts"])
        rx.refresh_from_db()
        self.assertFalse(rx.is_signed)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "contraindication")


class TestCrossDimensionUnitAdvisory(_EnforceBase):
    def test_cross_dimension_unit_is_advisory_not_block(self):
        """R4: dose_unit=mL against a mg rule is incomparable (cross-dimension) →
        DATA_MISSING advisory (caution), NOT a 409 block."""
        rx, _item = self._make_rx(dose=Decimal("7"), unit="mL")
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")

    def test_missing_unit_is_advisory_not_block(self):
        """R4: a structured dose with NO unit → DATA_MISSING advisory, not a 409."""
        rx, _item = self._make_rx(dose=Decimal("7"), unit="")
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")


class TestWeightBandedGateBlocks(_EnforceBase):
    def test_weight_banded_rule_no_weight_blocks_409(self):
        """R1: a weight-BANDED rule that matches age/route but is unselectable
        without a weight must WEIGHT_GATE → 409 (block), not advise-and-pass."""
        drug = Drug.objects.create(name="FAKE-Enf-WeightBand", generic_name="fake_enf_wb")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            weight_min_kg=Decimal("10"),
            weight_max_kg=Decimal("20"),
            min_per_dose=Decimal("1"),
            max_per_dose=Decimal("2"),
            absolute_max_dose=Decimal("2"),
            active=True,
        )
        # Patient with NO recorded weight.
        patient2 = Patient.objects.create(
            full_name="WB NoWeight", birth_date=date(1990, 1, 1), gender="F", cpf="33344455566"
        )
        enc2 = Encounter.objects.create(patient=patient2, professional=self.prof)
        rx = Prescription.objects.create(encounter=enc2, patient=patient2, prescriber=self.prof)
        PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            quantity=Decimal("5"),
            unit_of_measure="un",
            dose_amount=Decimal("1.5"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["code"], "dose_safety_block")
        rx.refresh_from_db()
        self.assertFalse(rx.is_signed)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "contraindication")


class TestAdvisoryIdempotency(_EnforceBase):
    def test_advisory_reeval_is_idempotent_one_audit_ack_preserved(self):
        """R3: re-evaluating the SAME advisory situation twice must write exactly
        ONE AuditLog (no spam) and must NOT wipe a prior acknowledgement."""
        from apps.core.models import AuditLog
        from apps.emr.services.dose_safety import DoseCheckService

        # A band-gap drug → NO_RULE_MATCH advisory (caution, non-blocking).
        drug = Drug.objects.create(name="FAKE-AdvIdem", generic_name="fake_advidem")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            age_min_days=0,
            age_max_days=28,  # neonate-only; adult patient → gap
            min_per_dose=Decimal("1"),
            max_per_dose=Decimal("2"),
            absolute_max_dose=Decimal("2"),
            active=True,
        )
        # Fresh patient with a real date birth_date + a recorded weight, so the
        # direct service call (no API reload) resolves age/weight cleanly.
        patient2 = Patient.objects.create(
            full_name="Adv Idem", birth_date=date(1990, 1, 1), gender="M", cpf="77788899900"
        )
        enc2 = Encounter.objects.create(patient=patient2, professional=self.prof)
        VitalSigns.objects.create(encounter=enc2, weight_kg=Decimal("10.00"))
        rx = Prescription.objects.create(encounter=enc2, patient=patient2, prescriber=self.prof)
        item = PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            quantity=Decimal("5"),
            unit_of_measure="un",
            dose_amount=Decimal("7"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )

        service = DoseCheckService(requesting_user=self.doctor)
        service.evaluate_prescription(rx, gate="sign")

        alert = AISafetyAlert.objects.get(
            prescription_item=item, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")
        first_audits = AuditLog.objects.filter(
            action="dose_no_rule_match", resource_id=str(item.id)
        ).count()
        self.assertEqual(first_audits, 1)

        # Clinician acknowledges the advisory.
        alert.acknowledge(self.doctor, reason="Faixa fora de cobertura; ciente e conferido.")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")

        # Re-evaluate the SAME situation (e.g. at the dispense gate).
        service.evaluate_prescription(rx, gate="dispense")

        alert.refresh_from_db()
        # Ack NOT wiped.
        self.assertEqual(alert.status, "acknowledged")
        self.assertEqual(alert.acknowledged_by, self.doctor)
        # No audit spam — still exactly one row for this advisory.
        self.assertEqual(
            AuditLog.objects.filter(action="dose_no_rule_match", resource_id=str(item.id)).count(),
            1,
        )

    def test_advisory_dose_change_reflags_and_audits(self):
        """FIX B: a NO_RULE_MATCH advisory is acknowledged at dose=5; the dose is
        then changed to 500 (still a band gap → still NO_RULE_MATCH). Because the
        advisory reason now embeds the dose, the changed dose changes the reason →
        the idempotency suppression no longer applies. A NEW AuditLog is written
        (the change is recorded for the flywheel) and the alert is re-flagged (the
        stale ack is NOT silently preserved)."""
        from apps.core.models import AuditLog
        from apps.emr.services.dose_safety import DoseCheckService

        # A band-gap drug → NO_RULE_MATCH advisory (caution, non-blocking).
        drug = Drug.objects.create(name="FAKE-AdvDoseChg", generic_name="fake_advdosechg")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            age_min_days=0,
            age_max_days=28,  # neonate-only; adult patient → gap
            min_per_dose=Decimal("1"),
            max_per_dose=Decimal("2"),
            absolute_max_dose=Decimal("2"),
            active=True,
        )
        patient2 = Patient.objects.create(
            full_name="Adv DoseChg", birth_date=date(1990, 1, 1), gender="M", cpf="44455566677"
        )
        enc2 = Encounter.objects.create(patient=patient2, professional=self.prof)
        VitalSigns.objects.create(encounter=enc2, weight_kg=Decimal("10.00"))
        rx = Prescription.objects.create(encounter=enc2, patient=patient2, prescriber=self.prof)
        item = PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            quantity=Decimal("5"),
            unit_of_measure="un",
            dose_amount=Decimal("5"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )

        service = DoseCheckService(requesting_user=self.doctor)
        service.evaluate_prescription(rx, gate="sign")

        alert = AISafetyAlert.objects.get(
            prescription_item=item, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")
        first_reason = alert.message
        # The dose is embedded in the advisory reason (stored at 4 decimals).
        self.assertIn("5.0000 mg", first_reason)
        self.assertEqual(
            AuditLog.objects.filter(action="dose_no_rule_match", resource_id=str(item.id)).count(),
            1,
        )

        # Clinician acknowledges the advisory.
        alert.acknowledge(self.doctor, reason="Faixa fora de cobertura; ciente e conferido.")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")

        # Change the dose to a very different value (still a gap → NO_RULE_MATCH).
        item.dose_amount = Decimal("500")
        item.save(update_fields=["dose_amount"])
        service.evaluate_prescription(rx, gate="dispense")

        alert.refresh_from_db()
        # Reason changed (dose embedded) → the change is NOT suppressed.
        self.assertNotEqual(alert.message, first_reason)
        self.assertIn("500.0000 mg", alert.message)
        # Ack NOT silently preserved — the alert is re-flagged.
        self.assertEqual(alert.status, "flagged")
        self.assertIsNone(alert.acknowledged_by)
        # A NEW AuditLog records the change (now two rows for this item).
        self.assertEqual(
            AuditLog.objects.filter(action="dose_no_rule_match", resource_id=str(item.id)).count(),
            2,
        )


class TestBandGapAdvisory(_EnforceBase):
    def test_band_gap_is_advisory_not_block(self):
        """Formulary HAS a rule for one age band; patient falls in a GAP →
        NO_RULE_MATCH advisory (caution), NOT a 409 block."""
        drug = Drug.objects.create(name="FAKE-GapDrug", generic_name="fake_gap")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        # Rule only covers neonates (0–28 days); our patient is an adult → gap.
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            age_min_days=0,
            age_max_days=28,
            min_per_dose=Decimal("1"),
            max_per_dose=Decimal("2"),
            absolute_max_dose=Decimal("2"),
            active=True,
        )
        rx, _item = self._make_rx(dose=Decimal("7"), drug=drug)
        resp = self._sign(rx)
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertTrue(rx.is_signed)
        alert = AISafetyAlert.objects.get(
            prescription_item__prescription=rx, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "caution")


class TestWeightGateSpoofClosed(_EnforceBase):
    def test_ack_not_preserved_after_dose_change_on_weight_gate(self):
        """A clinician acknowledges a WEIGHT_GATE, then edits the dose to a lethal
        value. Because the WEIGHT_GATE reason now embeds the dose, the changed dose
        changes the reason → the override-preservation predicate fails → the alert
        is re-flagged and the gate blocks again."""
        from apps.emr.services.dose_safety import DoseCheckService

        # Patient with NO weight → per_kg → WEIGHT_GATE (blocking).
        patient2 = Patient.objects.create(
            full_name="Spoof NoWeight", birth_date=date(1990, 1, 1), gender="F", cpf="12121212121"
        )
        enc2 = Encounter.objects.create(patient=patient2, professional=self.prof)
        rx = Prescription.objects.create(encounter=enc2, patient=patient2, prescriber=self.prof)
        item = PrescriptionItem.objects.create(
            prescription=rx,
            drug=make_perkg_drug(),
            quantity=Decimal("5"),
            unit_of_measure="un",
            dose_amount=Decimal("7"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=1,
        )

        service = DoseCheckService(requesting_user=self.doctor)
        service.evaluate_prescription(rx, gate="sign")
        alert = AISafetyAlert.objects.get(
            prescription_item=item, source="engine", alert_type="dose"
        )
        self.assertEqual(alert.severity, "contraindication")
        self.assertEqual(alert.status, "flagged")
        first_reason = alert.message

        # Clinician acknowledges the weight-gate.
        alert.acknowledge(self.doctor, reason="Peso será registrado em seguida; ciente.")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "acknowledged")

        # SPOOF: edit the dose to a lethal value, then re-evaluate.
        item.dose_amount = Decimal("9999")
        item.save(update_fields=["dose_amount"])
        service.evaluate_prescription(rx, gate="dispense")

        alert.refresh_from_db()
        # The reason changed (dose embedded) → ack must NOT be preserved.
        self.assertNotEqual(alert.message, first_reason)
        self.assertEqual(alert.status, "flagged")
        self.assertIsNone(alert.acknowledged_by)
        # Gate blocks again.
        self.assertTrue(DoseCheckService.has_blocking_dose_alert(rx))


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
        # No structured dose at all → DATA_MISSING → caution, NON-blocking.
        rx, _item = self._make_rx(dose=None)
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
