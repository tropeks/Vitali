"""Exhaustive unit tests for the deterministic DoseChecker engine (wedge PR B).

This is the LIFE-SAFETY matrix. The engine is pure (no DB writes), so most of
these tests build the formulary/rule in the DB only because the engine reads
``drug.formulary`` and ``formulary.dose_rules`` via the ORM — they assert ONLY
on the returned DoseVerdict, never on side-effects.

═══════════════════════════════════════════════════════════════════════════════
ILLUSTRATIVE TEST NUMBERS — NOT CLINICAL TRUTH.
The drugs, strengths and dose bands below are FABRICATED to exercise the engine
math. They are NOT a clinical formulary and MUST NOT be copied into production.
The real formulary is pharmacist-supplied external truth (decision D-T1); the
production tables stay empty until then.
═══════════════════════════════════════════════════════════════════════════════
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.pharmacy.services.dose_checker import DoseChecker, Verdict
from apps.test_utils import TenantTestCase

# ── ILLUSTRATIVE constants (fabricated; not clinical) ──────────────────────────
PER_KG_MIN = Decimal("0.5000")  # mg/kg lower bound (FAKE)
PER_KG_MAX = Decimal("1.0000")  # mg/kg upper bound (FAKE)
PER_KG_ABS_MAX = Decimal("50.0000")  # absolute ceiling in mg (FAKE)
PER_KG_MAX_DAILY = Decimal("60.0000")  # max mg/day (FAKE)

FIXED_MIN = Decimal("10.0000")  # mg (FAKE)
FIXED_MAX = Decimal("20.0000")  # mg (FAKE)
FIXED_ABS_MAX = Decimal("20.0000")  # mg (FAKE)


def make_per_kg_formulary():
    """Create an ILLUSTRATIVE per_kg formulary entry + rule. NOT clinical."""
    from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

    drug = Drug.objects.create(name="FAKE-PerKg-Drug", generic_name="fake_perkg")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="IV",
        is_injectable=True,
        is_high_alert=True,
        active=True,
    )
    rule = DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=PER_KG_MIN,
        max_per_kg=PER_KG_MAX,
        absolute_max_dose=PER_KG_ABS_MAX,
        max_per_day=PER_KG_MAX_DAILY,
        active=True,
    )
    return drug, formulary, rule


def make_fixed_formulary():
    """Create an ILLUSTRATIVE fixed formulary entry + rule. NOT clinical."""
    from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

    drug = Drug.objects.create(name="FAKE-Fixed-Drug", generic_name="fake_fixed")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="PO",
        active=True,
    )
    rule = DoseRule.objects.create(
        formulary=formulary,
        basis="fixed",
        dose_unit="mg",
        min_per_dose=FIXED_MIN,
        max_per_dose=FIXED_MAX,
        absolute_max_dose=FIXED_ABS_MAX,
        active=True,
    )
    return drug, formulary, rule


class _Base(TenantTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.fresh = self.now - timedelta(days=1)

    def check_perkg(self, drug, *, dose, weight, recorded_at=None, freq=None, unit="mg"):
        return DoseChecker.check(
            drug=drug,
            dose_amount=dose,
            dose_unit=unit,
            route="IV",
            frequency_per_day=freq,
            patient_age_days=3650,
            weight_kg=weight,
            weight_recorded_at=recorded_at if recorded_at is not None else self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )

    def check_fixed(self, drug, *, dose, freq=None, unit="mg"):
        return DoseChecker.check(
            drug=drug,
            dose_amount=dose,
            dose_unit=unit,
            route="PO",
            frequency_per_day=freq,
            patient_age_days=12000,
            weight_kg=Decimal("70.00"),
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )


class TestDoseCheckerPerKg(_Base):
    def test_safe_within_per_kg_band(self):
        drug, _f, _r = make_per_kg_formulary()
        # 10kg × [0.5, 1.0] = [5, 10] mg; dose 7 mg, 1×/dia (7 ≤ 60/dia) → SAFE
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.expected_low, Decimal("5.0000"))
        self.assertEqual(v.expected_high, Decimal("10.0000"))

    def test_out_of_range_over_per_kg_max(self):
        drug, _f, _r = make_per_kg_formulary()
        # 10kg → high 10mg; dose 11mg → OUT_OF_RANGE (and under abs cap 50)
        v = self.check_perkg(drug, dose=Decimal("11"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)

    def test_under_per_kg_min_out_of_range(self):
        drug, _f, _r = make_per_kg_formulary()
        # 10kg → low 5mg; dose 4mg → OUT_OF_RANGE (under-dose)
        v = self.check_perkg(drug, dose=Decimal("4"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)

    def test_absolute_max_fires_on_weight_typo_even_when_per_kg_passes(self):
        """700kg weight-typo: per-kg band becomes [350,700], dose 60 'passes' the
        band but MUST be caught by the absolute ceiling (50mg)."""
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("60"), weight=Decimal("700"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertIn("teto absoluto", v.reason)

    def test_max_per_day_exceeded_blocks_when_per_dose_ok(self):
        drug, _f, _r = make_per_kg_formulary()
        # 10kg → per-dose band [5,10]; dose 10 ok, but 10×7=70 > 60/day → OUT_OF_RANGE
        v = self.check_perkg(drug, dose=Decimal("10"), weight=Decimal("10"), freq=7)
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertIn("diária", v.reason)

    def test_max_per_day_within_is_safe(self):
        drug, _f, _r = make_per_kg_formulary()
        # 10×5=50 <= 60/day → SAFE (dose 10 within [5,10])
        v = self.check_perkg(drug, dose=Decimal("10"), weight=Decimal("10"), freq=5)
        self.assertEqual(v.verdict, Verdict.SAFE)

    def test_missing_weight_weight_gate(self):
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("7"), weight=None)
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)

    def test_stale_weight_weight_gate(self):
        drug, _f, _r = make_per_kg_formulary()
        stale = self.now - timedelta(days=91)
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"), recorded_at=stale)
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)

    def test_weight_recorded_at_none_is_weight_gate(self):
        drug, _f, _r = make_per_kg_formulary()
        v = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("7"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=Decimal("10"),
            weight_recorded_at=None,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)

    def test_boundary_equals_high_allowed(self):
        drug, _f, _r = make_per_kg_formulary()
        # 10kg → high exactly 10mg; dose == 10, 1×/dia → SAFE (boundary allowed)
        v = self.check_perkg(drug, dose=Decimal("10"), weight=Decimal("10"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)

    def test_boundary_equals_low_allowed(self):
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("5"), weight=Decimal("10"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)

    def test_boundary_equals_absolute_max_allowed(self):
        drug, _f, _r = make_per_kg_formulary()
        # 100kg → band [50,100]; dose == abs cap 50, 1×/dia → SAFE (== allowed)
        v = self.check_perkg(drug, dose=Decimal("50"), weight=Decimal("100"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)


class TestDoseCheckerFixed(_Base):
    def test_safe_within_fixed_band(self):
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=Decimal("15"))
        self.assertEqual(v.verdict, Verdict.SAFE)

    def test_out_of_range_over_fixed_max(self):
        drug, _f, _r = make_fixed_formulary()
        # band [10,20], abs cap 20; dose 21 → OUT_OF_RANGE (abs cap fires)
        v = self.check_fixed(drug, dose=Decimal("21"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)

    def test_boundary_fixed_max_allowed(self):
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=Decimal("20"))
        self.assertEqual(v.verdict, Verdict.SAFE)


class TestDoseCheckerDataAndApplicability(_Base):
    def test_unit_mismatch_blocks_never_coerced(self):
        drug, _f, _r = make_fixed_formulary()
        # rule unit mg, prescribed mcg → UNIT_MISMATCH (NEVER coerce mg↔mcg).
        # This is a BLOCKING verdict: a 1000x error must never sail through.
        v = self.check_fixed(drug, dose=Decimal("15"), unit="mcg")
        self.assertEqual(v.verdict, Verdict.UNIT_MISMATCH)
        # Reason must embed the dose amount and both units.
        self.assertIn("15", v.reason)
        self.assertIn("mcg", v.reason)
        self.assertIn("mg", v.reason)

    def test_missing_dose_data_missing(self):
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=None)
        self.assertEqual(v.verdict, Verdict.DATA_MISSING)

    def test_cross_dimension_unit_is_data_missing_not_block(self):
        """R4: mL (volume) vs a mg (mass) rule is incomparable — it can't be a
        1000x typo, so it degrades to DATA_MISSING (advisory), NOT a hard block."""
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=Decimal("15"), unit="mL")
        self.assertEqual(v.verdict, Verdict.DATA_MISSING)
        self.assertIn("mL", v.reason)
        self.assertIn("mg", v.reason)

    def test_missing_unit_is_data_missing(self):
        """R4: a dose with NO unit can't be compared → DATA_MISSING (advisory)."""
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=Decimal("15"), unit=None)
        self.assertEqual(v.verdict, Verdict.DATA_MISSING)
        self.assertIn("mg", v.reason)

    def test_mass_family_mismatch_still_blocks(self):
        """R4 guard: g vs mg (both mass-family) is the dangerous off-by-1000 →
        UNIT_MISMATCH (blocking), must stay blocking."""
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=Decimal("15"), unit="g")
        self.assertEqual(v.verdict, Verdict.UNIT_MISMATCH)

    def test_volume_family_mismatch_blocks(self):
        """FIX A: a same-dimension VOLUME mismatch (mL vs L) is an off-by-1000
        confusion within the volume family and MUST hard-block, exactly like the
        mass family. Volume units are not in DOSE_UNIT_CHOICES today; we test the
        engine logic directly with a stub rule (do NOT add mL/L to the model)."""

        class _Rule:
            id = None
            dose_unit = "L"

        rule = _Rule()
        # Both belong to the volume family → block.
        self.assertTrue(DoseChecker._same_dimension("mL", rule.dose_unit))
        self.assertTrue(DoseChecker._same_dimension("L", "mL"))
        # Cross-dimension (volume vs mass) is NOT the same family → advise.
        self.assertFalse(DoseChecker._same_dimension("mL", "mg"))
        self.assertFalse(DoseChecker._same_dimension("L", "g"))

    def test_same_dimension_unknown_unit_is_not_same_family(self):
        """An unknown unit shares no family → cross-dimension (advisory)."""
        self.assertFalse(DoseChecker._same_dimension("IU", "mg"))
        self.assertFalse(DoseChecker._same_dimension("foo", "bar"))

    def test_drug_not_in_formulary_not_applicable(self):
        from apps.pharmacy.models import Drug

        drug = Drug.objects.create(name="FAKE-Uncurated", generic_name="fake_unc")
        v = self.check_fixed(drug, dose=Decimal("15"))
        self.assertEqual(v.verdict, Verdict.NOT_APPLICABLE)

    def test_inactive_formulary_not_applicable(self):
        drug, formulary, _r = make_fixed_formulary()
        formulary.active = False
        formulary.save(update_fields=["active"])
        v = self.check_fixed(drug, dose=Decimal("15"))
        self.assertEqual(v.verdict, Verdict.NOT_APPLICABLE)

    def test_no_matching_age_band_no_rule_match(self):
        """Formulary HAS active rules, but none cover this patient's band → GAP.

        This must be NO_RULE_MATCH (advisory), NOT a silent NOT_APPLICABLE: the
        drug IS dose-checkable, we just couldn't cover this patient.
        """
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-NeonatalOnly", generic_name="fake_neo")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        # Rule only applies to 0–28 days; our patient is 3650 days → no match.
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
        v = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("1.5"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=None,
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(v.verdict, Verdict.NO_RULE_MATCH)

    def test_formulary_with_no_active_rules_not_applicable(self):
        """Active formulary but ZERO active rules (not yet authored) → NOT_APPLICABLE."""
        from apps.pharmacy.models import Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-NoRules", generic_name="fake_norules")
        MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        v = self.check_fixed(drug, dose=Decimal("15"))
        self.assertEqual(v.verdict, Verdict.NOT_APPLICABLE)

    def test_daily_cap_with_missing_frequency_is_data_missing(self):
        """Per-dose in range, daily cap exists, but frequency unknown → DATA_MISSING.

        We must not overclaim SAFE: the daily dimension is unverifiable.
        """
        drug, _f, _r = make_per_kg_formulary()  # max_per_day=60 set
        # 10kg → band [5,10]; dose 7 in range; freq None → can't check daily cap.
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"), freq=None)
        self.assertEqual(v.verdict, Verdict.DATA_MISSING)
        self.assertIn("frequência diária", v.reason)
        self.assertIn("60", v.reason)
        self.assertEqual(v.expected_low, Decimal("5.0000"))
        self.assertEqual(v.expected_high, Decimal("10.0000"))

    def test_engine_error_when_check_throws(self):
        """A drug-like object whose .formulary access raises → ENGINE_ERROR (advisory)."""

        class Boom:
            @property
            def formulary(self):
                raise RuntimeError("simulated engine fault")

        v = DoseChecker.check(
            drug=Boom(),
            dose_amount=Decimal("5"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=Decimal("10"),
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(v.verdict, Verdict.ENGINE_ERROR)


class TestDoseCheckerWeightGateOnMissingWeight(_Base):
    """R1: a weight-DEPENDENT rule that matches age/route but is unselectable
    because the patient weight is unknown must WEIGHT_GATE (block), never fall
    through to NO_RULE_MATCH (advisory) — a fail-safe escape would let a
    pediatric weight-banded rule sail past the hard block."""

    def _weight_banded_drug(self):
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-WeightBand", generic_name="fake_wb")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        # Weight-BANDED fixed rule (10–20 kg). Matches age/route, but the band
        # can't be confirmed without a weight.
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
        return drug

    def test_weight_banded_rule_missing_weight_weight_gates(self):
        drug = self._weight_banded_drug()
        v = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("1.5"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=None,
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)
        self.assertIsNone(v.rule_id)
        self.assertIn("peso", v.reason)
        self.assertIn("1.5 mg", v.reason)

    def test_unitless_dose_amount_embedded_so_edit_reblocks(self):
        """A unit-less dose (amount present, unit missing) hitting the selection
        WEIGHT_GATE must still embed the AMOUNT in the reason. Otherwise the reason
        is dose-static and an acknowledged block could be bypassed by editing only
        the amount (the override-preservation predicate keys on the message)."""
        drug = self._weight_banded_drug()

        def gate_reason(amount):
            return DoseChecker.check(
                drug=drug,
                dose_amount=Decimal(amount),
                dose_unit=None,  # no unit
                route="IV",
                frequency_per_day=None,
                patient_age_days=3650,
                weight_kg=None,
                weight_recorded_at=self.fresh,
                now=self.now,
                weight_staleness_days=90,
            ).reason

        r10 = gate_reason("10")
        r1000 = gate_reason("1000")
        # The amount must appear (even without a unit) and differ across doses, so a
        # dose edit changes the message → the preserved override is reset → re-block.
        self.assertIn("10", r10)
        self.assertIn("1000", r1000)
        self.assertNotEqual(r10, r1000)

    def test_per_kg_no_band_missing_weight_still_weight_gates(self):
        """Regression guard: a per_kg rule with NO weight band + no weight is still
        selected and WEIGHT_GATEs at step 4 (must stay blocking)."""
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("7"), weight=None)
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)

    def test_weight_known_outside_all_bands_is_no_rule_match(self):
        """R1 negative: rules exist, weight IS known, patient genuinely outside all
        bands → NO_RULE_MATCH (advisory), NOT a WEIGHT_GATE block."""
        drug = self._weight_banded_drug()  # band 10–20 kg
        v = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("1.5"),
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=Decimal("80"),  # outside 10–20 kg
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(v.verdict, Verdict.NO_RULE_MATCH)


class TestDoseCheckerRuleSelection(_Base):
    def test_most_specific_band_chosen_when_multiple_match(self):
        """A narrow age band wins over a broad one when both match."""
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-MultiBand", generic_name="fake_mb")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="PO",
            active=True,
        )
        # Broad rule: any age, band [10,20]
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            min_per_dose=Decimal("10"),
            max_per_dose=Decimal("20"),
            absolute_max_dose=Decimal("20"),
            active=True,
        )
        # Narrow rule: 3000–4000 days, band [1,2] — more specific, should win.
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            age_min_days=3000,
            age_max_days=4000,
            min_per_dose=Decimal("1"),
            max_per_dose=Decimal("2"),
            absolute_max_dose=Decimal("2"),
            active=True,
        )
        # Patient 3650 days, dose 15 mg. Under broad band it's SAFE; under the
        # narrow (correct) band it's OUT_OF_RANGE. The narrow band must win.
        v = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("15"),
            dose_unit="mg",
            route="PO",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=None,
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)

    def test_tie_break_favors_stricter_lower_ceiling(self):
        """Two equally-specific rules (same spans, same route-rank) → the one with
        the LOWER absolute_max_dose (stricter) must win, never an arbitrary UUID."""
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-TieBreak", generic_name="fake_tie")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="PO",
            active=True,
        )
        common = {
            "formulary": formulary,
            "basis": "fixed",
            "dose_unit": "mg",
            "age_min_days": 0,
            "age_max_days": 40000,
            "min_per_dose": Decimal("1"),
            "max_per_dose": Decimal("100"),
            "route": "PO",
            "active": True,
        }
        # Looser rule (higher ceiling).
        loose = DoseRule.objects.create(absolute_max_dose=Decimal("100"), **common)
        # Stricter rule (lower ceiling) — must be selected on the tie.
        strict = DoseRule.objects.create(absolute_max_dose=Decimal("50"), **common)

        chosen = DoseChecker._select_rule(
            active_rules=list(formulary.dose_rules.filter(active=True)),
            formulary=formulary,
            patient_age_days=3650,
            weight_kg=None,
            route="PO",
        )
        self.assertEqual(chosen.id, strict.id)
        self.assertNotEqual(chosen.id, loose.id)
