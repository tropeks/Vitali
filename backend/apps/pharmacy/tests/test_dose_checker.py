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
        # 10kg × [0.5, 1.0] = [5, 10] mg; dose 7 mg → SAFE
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"))
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
        # 10kg → high exactly 10mg; dose == 10 → SAFE (boundary allowed)
        v = self.check_perkg(drug, dose=Decimal("10"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.SAFE)

    def test_boundary_equals_low_allowed(self):
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("5"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.SAFE)

    def test_boundary_equals_absolute_max_allowed(self):
        drug, _f, _r = make_per_kg_formulary()
        # 100kg → band [50,100]; dose == abs cap 50 → SAFE (== allowed)
        v = self.check_perkg(drug, dose=Decimal("50"), weight=Decimal("100"))
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
    def test_unit_mismatch_data_missing_never_coerced(self):
        drug, _f, _r = make_fixed_formulary()
        # rule unit mg, prescribed mcg → DATA_MISSING (NEVER coerce mg↔mcg)
        v = self.check_fixed(drug, dose=Decimal("15"), unit="mcg")
        self.assertEqual(v.verdict, Verdict.DATA_MISSING)

    def test_missing_dose_data_missing(self):
        drug, _f, _r = make_fixed_formulary()
        v = self.check_fixed(drug, dose=None)
        self.assertEqual(v.verdict, Verdict.DATA_MISSING)

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

    def test_no_matching_age_band_not_applicable(self):
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
        self.assertEqual(v.verdict, Verdict.NOT_APPLICABLE)

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
