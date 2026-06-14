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
        validated=True,
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
        validated=True,
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
            validated=True,
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
            validated=True,
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
            validated=True,
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
            validated=True,
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
        the LOWER absolute_max_dose (stricter) must win, never an arbitrary UUID.

        NOTE: The rules have DIFFERENT natural keys (different age bounds) but the
        SAME age span (40000 days), so the specificity key produces a true tie
        resolved by absolute_max_dose. This satisfies the doserule_natural_key
        UniqueConstraint while still exercising the tie-break logic.
        """
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-TieBreak", generic_name="fake_tie")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("1.000"),
            strength_unit="mg",
            route="PO",
            active=True,
        )
        shared = {
            "formulary": formulary,
            "basis": "fixed",
            "dose_unit": "mg",
            "min_per_dose": Decimal("1"),
            "max_per_dose": Decimal("100"),
            "route": "PO",
            "active": True,
            "validated": True,
        }
        # Both rules have the SAME age span (40000 days) but DIFFERENT age bounds,
        # so they have different natural keys (no UniqueConstraint violation) while
        # still producing an equal specificity score for the span dimension.
        # Patient age 3650 falls in both [0, 40000] and [1, 40001].
        # Looser rule (higher ceiling, bounds 0–40000).
        loose = DoseRule.objects.create(
            age_min_days=0, age_max_days=40000, absolute_max_dose=Decimal("100"), **shared
        )
        # Stricter rule (lower ceiling, bounds 1–40001) — must be selected on the tie.
        strict = DoseRule.objects.create(
            age_min_days=1, age_max_days=40001, absolute_max_dose=Decimal("50"), **shared
        )

        chosen = DoseChecker._select_rule(
            active_rules=list(formulary.dose_rules.filter(active=True, validated=True)),
            formulary=formulary,
            patient_age_days=3650,
            weight_kg=None,
            route="PO",
            frequency_per_day=None,
            prescribed_role="maintenance",
        )
        self.assertEqual(chosen.id, strict.id)
        self.assertNotEqual(chosen.id, loose.id)


# ═══════════════════════════════════════════════════════════════════════════════
# Dose-engine v2 — AXIS 1 (frequency band), AXIS 2 (loading vs maintenance),
# AXIS 3 (block vs advise). ILLUSTRATIVE numbers — NOT clinical truth.
# ═══════════════════════════════════════════════════════════════════════════════


def _freq_banded_formulary():
    """ILLUSTRATIVE: aminoglycoside-style dual paradigm via the AXIS-1 freq band.

    Extended-interval rule: freq 1–1, higher band [4,6] mg/kg.
    Traditional rule:       freq 2–4, lower band  [1.5,2.5] mg/kg.
    Same drug/age/route; they coexist and are disambiguated ONLY by frequency.
    NOT clinical.
    """
    from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

    drug = Drug.objects.create(name="FAKE-FreqBand", generic_name="fake_freqband")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="IV",
        is_injectable=True,
        is_high_alert=True,
        active=True,
    )
    extended = DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=Decimal("4.0000"),
        max_per_kg=Decimal("6.0000"),
        absolute_max_dose=Decimal("700.0000"),
        freq_min_per_day=1,
        freq_max_per_day=1,
        active=True,
        validated=True,
    )
    traditional = DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=Decimal("1.5000"),
        max_per_kg=Decimal("2.5000"),
        absolute_max_dose=Decimal("700.0000"),
        freq_min_per_day=2,
        freq_max_per_day=4,
        active=True,
        validated=True,
    )
    return drug, formulary, extended, traditional


class TestDoseCheckerFrequencyBand(_Base):
    """AXIS 1: two rules for the same drug/age, disambiguated by frequency."""

    def test_freq1_selects_extended_band(self):
        drug, _f, extended, _trad = _freq_banded_formulary()
        # 10 kg, freq 1 → extended band [40,60]; dose 50 → SAFE under extended.
        v = self.check_perkg(drug, dose=Decimal("50"), weight=Decimal("10"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.rule_id, extended.id)
        self.assertEqual(v.expected_low, Decimal("40.0000"))
        self.assertEqual(v.expected_high, Decimal("60.0000"))

    def test_freq3_selects_traditional_band(self):
        drug, _f, _ext, traditional = _freq_banded_formulary()
        # 10 kg, freq 3 → traditional band [15,25]; dose 20 → SAFE under traditional.
        v = self.check_perkg(drug, dose=Decimal("20"), weight=Decimal("10"), freq=3)
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.rule_id, traditional.id)
        self.assertEqual(v.expected_low, Decimal("15.0000"))
        self.assertEqual(v.expected_high, Decimal("25.0000"))

    def test_extended_dose_at_traditional_freq_flags(self):
        """A dose fine for extended (50 mg) but prescribed at a traditional
        frequency (freq 3) is checked against the traditional band [15,25] → it
        is OUT_OF_RANGE only at the wrong frequency."""
        drug, _f, _ext, _trad = _freq_banded_formulary()
        v = self.check_perkg(drug, dose=Decimal("50"), weight=Decimal("10"), freq=3)
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)

    def test_missing_frequency_with_freq_banded_rules_is_no_rule_match(self):
        """FAIL-SAFE: every rule is freq-banded; an unknown frequency cannot
        confirm the regimen → NO_RULE_MATCH advisory, never a wrong selection."""
        drug, _f, _ext, _trad = _freq_banded_formulary()
        v = self.check_perkg(drug, dose=Decimal("50"), weight=Decimal("10"), freq=None)
        self.assertEqual(v.verdict, Verdict.NO_RULE_MATCH)

    def test_frequency_outside_all_bands_is_no_rule_match(self):
        """freq 6 is above both bands (extended 1, traditional ≤4) → NO_RULE_MATCH."""
        drug, _f, _ext, _trad = _freq_banded_formulary()
        v = self.check_perkg(drug, dose=Decimal("20"), weight=Decimal("10"), freq=6)
        self.assertEqual(v.verdict, Verdict.NO_RULE_MATCH)


def _loading_maintenance_formulary():
    """ILLUSTRATIVE: vancomicina-style loading vs maintenance (AXIS 2).

    Loading rule (dose_role=loading): higher band [25,30] mg/kg.
    Maintenance rule (default):       lower band  [10,20] mg/kg.
    NOT clinical.
    """
    from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

    drug = Drug.objects.create(name="FAKE-LoadMaint", generic_name="fake_loadmaint")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="IV",
        is_injectable=True,
        is_high_alert=True,
        active=True,
    )
    maintenance = DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=Decimal("10.0000"),
        max_per_kg=Decimal("20.0000"),
        absolute_max_dose=Decimal("2000.0000"),
        dose_role="maintenance",
        active=True,
        validated=True,
    )
    loading = DoseRule.objects.create(
        formulary=formulary,
        basis="per_kg",
        dose_unit="mg",
        min_per_kg=Decimal("25.0000"),
        max_per_kg=Decimal("30.0000"),
        absolute_max_dose=Decimal("3000.0000"),
        dose_role="loading",
        active=True,
        validated=True,
    )
    return drug, formulary, maintenance, loading


class TestDoseCheckerDoseRole(_Base):
    """AXIS 2: loading rule selected ONLY for an explicitly-loading item."""

    def _check(self, drug, *, dose, weight, freq=1, role=None):
        return DoseChecker.check(
            drug=drug,
            dose_amount=dose,
            dose_unit="mg",
            route="IV",
            frequency_per_day=freq,
            patient_age_days=3650,
            weight_kg=weight,
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
            dose_role=role,
        )

    def test_loading_item_uses_loading_band(self):
        drug, _f, _maint, loading = _loading_maintenance_formulary()
        # 10 kg, loading band [250,300]; dose 280, marked loading → SAFE under loading.
        v = self._check(drug, dose=Decimal("280"), weight=Decimal("10"), role="loading")
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.rule_id, loading.id)
        self.assertEqual(v.expected_low, Decimal("250.0000"))
        self.assertEqual(v.expected_high, Decimal("300.0000"))

    def test_unmarked_loading_magnitude_dose_checked_vs_maintenance_out_of_range(self):
        """A loading-magnitude dose (280 mg) with NO role → screened against the
        lower MAINTENANCE band [100,200] → OUT_OF_RANGE (fail-safe over-flag)."""
        drug, _f, maintenance, _loading = _loading_maintenance_formulary()
        v = self._check(drug, dose=Decimal("280"), weight=Decimal("10"), role="")
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertEqual(v.rule_id, maintenance.id)

    def test_none_role_normalizes_to_maintenance(self):
        drug, _f, maintenance, _loading = _loading_maintenance_formulary()
        # dose 150 in maintenance band [100,200]; role None → maintenance → SAFE.
        v = self._check(drug, dose=Decimal("150"), weight=Decimal("10"), role=None)
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.rule_id, maintenance.id)


def _advise_formulary(enforcement="advise"):
    """ILLUSTRATIVE: an opioid-style rule with no hard ceiling (AXIS 3).
    band [0.5,1.0] mg/kg, abs cap 50; enforcement='advise'. NOT clinical."""
    from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

    drug = Drug.objects.create(name=f"FAKE-Advise-{enforcement}", generic_name="fake_advise")
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
        enforcement=enforcement,
        active=True,
        validated=True,
    )
    return drug


class TestDoseCheckerEnforcement(_Base):
    """AXIS 3: enforcement is echoed on the verdict; WEIGHT_GATE/UNIT_MISMATCH
    stay blocking regardless of enforcement mode."""

    def test_out_of_range_echoes_advise_enforcement(self):
        drug = _advise_formulary("advise")
        # 10 kg → band [5,10]; dose 40 → OUT_OF_RANGE, enforcement carried as advise.
        v = self.check_perkg(drug, dose=Decimal("40"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertEqual(v.enforcement, "advise")

    def test_out_of_range_default_block_enforcement(self):
        drug = _advise_formulary("block")
        v = self.check_perkg(drug, dose=Decimal("40"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertEqual(v.enforcement, "block")

    def test_safe_echoes_enforcement(self):
        drug = _advise_formulary("advise")
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.enforcement, "advise")

    def test_absolute_ceiling_breach_always_blocks_even_under_advise(self):
        """Adversarial-review fix: an 'advise' rule (opioid, no therapeutic
        ceiling) may titrate ABOVE the expected range as a caution — but breaching
        the universal absolute_max_dose must STILL hard-block (enforcement='block'),
        or a 700kg-typo lethal dose would slip past on a mere caution."""
        drug = _advise_formulary("advise")
        # 10 kg → band [5,10], abs cap 50. dose 60 > 50 → absolute-ceiling breach.
        v = self.check_perkg(drug, dose=Decimal("60"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertIn("teto absoluto", v.reason)
        self.assertEqual(v.enforcement, "block")  # forced, despite rule=advise


class TestDoseCheckerV2ReviewFixes(_Base):
    """Adversarial-review fixes for the dose-engine v2 axes."""

    def test_missing_weight_weight_gates_even_when_frequency_also_missing(self):
        """Fix: for a drug whose ONLY rules are frequency-banded per_kg (e.g. an
        aminoglycoside), a per-kg order with NO weight AND no frequency must still
        WEIGHT_GATE (block) — not slip past as a NO_RULE_MATCH advisory."""
        drug, _f, _ext, _trad = _freq_banded_formulary()
        v = self.check_perkg(drug, dose=Decimal("50"), weight=None, freq=None)
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)

    def test_strictest_absolute_ceiling_across_overlapping_candidates(self):
        """Fix: when two rules overlap on the prescribed frequency, the narrower
        (more-specific) rule supplies the band, but the absolute ceiling enforced
        is the STRICTEST (lowest) among ALL matching rules — a narrower-but-looser
        rule can't raise the hard cap."""
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-Overlap", generic_name="fake_overlap")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("10.000"),
            strength_unit="mg",
            route="IV",
            is_injectable=True,
            is_high_alert=True,
            active=True,
        )
        # Broad rule: freq 1–4, STRICT ceiling 50.
        DoseRule.objects.create(
            formulary=formulary,
            basis="per_kg",
            dose_unit="mg",
            min_per_kg=Decimal("0.0000"),
            max_per_kg=Decimal("5.0000"),
            absolute_max_dose=Decimal("50.0000"),
            freq_min_per_day=1,
            freq_max_per_day=4,
            active=True,
            validated=True,
        )
        # Narrower (freq 2–2) but LOOSER: wide band + ceiling 500.
        narrow_loose = DoseRule.objects.create(
            formulary=formulary,
            basis="per_kg",
            dose_unit="mg",
            min_per_kg=Decimal("0.0000"),
            max_per_kg=Decimal("50.0000"),
            absolute_max_dose=Decimal("500.0000"),
            freq_min_per_day=2,
            freq_max_per_day=2,
            active=True,
            validated=True,
        )
        # 10 kg, freq 2: both match; narrow_loose wins the band (freq span 0),
        # but the enforced ceiling = min(50, 500) = 50. dose 100 sits inside
        # narrow_loose's band [0,500] yet breaches the strict ceiling 50.
        v = self.check_perkg(drug, dose=Decimal("100"), weight=Decimal("10"), freq=2)
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertEqual(v.rule_id, narrow_loose.id)  # band from the specific rule
        self.assertIn("teto absoluto", v.reason)
        self.assertEqual(v.max_per_dose, Decimal("50.0000"))  # strictest ceiling
        self.assertEqual(v.enforcement, "block")

    def test_weight_gate_on_advise_rule_stays_block_default(self):
        """A WEIGHT_GATE keeps enforcement='block' even on an advise rule — the
        orchestrator must always block it (you cannot dose per-kg without a weight)."""
        drug = _advise_formulary("advise")
        v = self.check_perkg(drug, dose=Decimal("7"), weight=None)
        self.assertEqual(v.verdict, Verdict.WEIGHT_GATE)
        self.assertEqual(v.enforcement, "block")

    def test_unit_mismatch_on_advise_rule_stays_block_default(self):
        drug = _advise_formulary("advise")
        # mcg vs mg rule, same mass family → UNIT_MISMATCH, enforcement stays block.
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"), unit="mcg")
        self.assertEqual(v.verdict, Verdict.UNIT_MISMATCH)
        self.assertEqual(v.enforcement, "block")


class TestDoseEngineV2BackwardCompat(_Base):
    """Regression guard: a rule with NONE of the new fields set behaves EXACTLY
    as before — maintenance role, block enforcement, any frequency matches."""

    def test_legacy_rule_unchanged_safe(self):
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("7"), weight=Decimal("10"), freq=1)
        self.assertEqual(v.verdict, Verdict.SAFE)
        self.assertEqual(v.enforcement, "block")

    def test_legacy_rule_matches_any_frequency(self):
        drug, _f, _r = make_per_kg_formulary()
        # No freq band on the rule → matches freq 1 and freq 4 identically.
        self.assertEqual(
            self.check_perkg(drug, dose=Decimal("10"), weight=Decimal("10"), freq=1).verdict,
            Verdict.SAFE,
        )
        # freq 4 → 10×4=40 ≤ 60/day cap → still SAFE.
        self.assertEqual(
            self.check_perkg(drug, dose=Decimal("10"), weight=Decimal("10"), freq=4).verdict,
            Verdict.SAFE,
        )

    def test_legacy_rule_out_of_range_blocks(self):
        drug, _f, _r = make_per_kg_formulary()
        v = self.check_perkg(drug, dose=Decimal("40"), weight=Decimal("10"))
        self.assertEqual(v.verdict, Verdict.OUT_OF_RANGE)
        self.assertEqual(v.enforcement, "block")


# ═══════════════════════════════════════════════════════════════════════════════
# S29-02: validated=True gate. A DoseRule only enforces when validated=True.
# Illustrative numbers — NOT clinical truth.
# ═══════════════════════════════════════════════════════════════════════════════


class TestDoseCheckerValidatedGate(_Base):
    """The DoseChecker must ignore DoseRules with validated=False.

    A rule that is active=True but validated=False is inert: the engine treats
    it as if it does not exist. Only after a human pharmacist sets validated=True
    does the rule participate in dose enforcement.
    """

    def _make_gated_formulary(self, *, validated: bool):
        """ILLUSTRATIVE formulary + fixed rule. NOT clinical."""
        from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary

        drug = Drug.objects.create(name="FAKE-GatedDrug", generic_name="fake_gated")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("10.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            min_per_dose=Decimal("5.0000"),
            max_per_dose=Decimal("15.0000"),
            absolute_max_dose=Decimal("15.0000"),
            active=True,
            validated=validated,
        )
        return drug

    def test_non_validated_rule_is_ignored_by_checker(self):
        """Key gating proof (S29-02):

        1. A DoseRule with active=True, validated=False covering this patient
           must NOT enforce — the checker returns NOT_APPLICABLE (no active
           validated rules), never SAFE or OUT_OF_RANGE.
        2. After the same rule is set validated=True and saved, an in-range
           dose must return SAFE — the gate is now open.
        """
        from apps.pharmacy.models import DoseRule

        # Phase 1: rule exists but is NOT validated → invisible to the checker.
        drug = self._make_gated_formulary(validated=False)
        v_before = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("10"),  # in-range (band [5,15])
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=None,
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        # With no validated rules the engine sees an empty active-rules list →
        # NOT_APPLICABLE (advisory gap), never a false SAFE.
        self.assertEqual(
            v_before.verdict,
            Verdict.NOT_APPLICABLE,
            f"Expected NOT_APPLICABLE for unvalidated rule, got {v_before.verdict}: {v_before.reason}",
        )

        # Phase 2: pharmacist validates the rule → it must now enforce.
        rule = DoseRule.objects.get(formulary__drug=drug)
        rule.validated = True
        rule.save(update_fields=["validated"])

        v_after = DoseChecker.check(
            drug=drug,
            dose_amount=Decimal("10"),  # same in-range dose
            dose_unit="mg",
            route="IV",
            frequency_per_day=None,
            patient_age_days=3650,
            weight_kg=None,
            weight_recorded_at=self.fresh,
            now=self.now,
            weight_staleness_days=90,
        )
        self.assertEqual(
            v_after.verdict,
            Verdict.SAFE,
            f"Expected SAFE after validation, got {v_after.verdict}: {v_after.reason}",
        )
