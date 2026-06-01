"""
Dose-safety wedge PR A — MedicationFormulary & DoseRule schema tests.

PURE SCHEMA. No clinical dose numbers are asserted as correct here — the
placeholder figures below exist only to exercise persistence, Decimal
precision, and the model-layer invariants. The curated formulary + real dose
bands are pharmacist-supplied external truth that lands with the deterministic
engine in PR B.

Covered:
  - MedicationFormulary / DoseRule create + Decimal precision (no float drift)
  - "is this drug dose-checkable?" predicate = formulary row exists
  - DoseRule basis="per_kg" (per-kg band) AND basis="fixed" (absolute band)
  - absolute_max_dose is mandatory (NOT NULL); clean() per-basis invariants
  - age bands stored in DAYS (neonatal granularity)
  - unit fields constrained to the shared mass-only choices
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary
from apps.test_utils import TenantTestCase


class TestMedicationFormulary(TenantTestCase):
    def setUp(self):
        self.drug = Drug.objects.create(
            name="Placeholder Inj 10mg/mL",
            generic_name="placeholder",
            controlled_class="none",
        )

    def test_formulary_create_with_decimal_precision(self):
        entry = MedicationFormulary.objects.create(
            drug=self.drug,
            strength_value=Decimal("10.250"),
            strength_unit="mg",
            volume_value=Decimal("1.000"),
            volume_unit="mL",
            route=MedicationFormulary.Route.IV,
            is_injectable=True,
            is_high_alert=True,
        )
        entry.refresh_from_db()
        # Values must round-trip as Decimal, not float — assert exact + type.
        self.assertEqual(entry.strength_value, Decimal("10.250"))
        self.assertIsInstance(entry.strength_value, Decimal)
        self.assertEqual(entry.volume_value, Decimal("1.000"))
        self.assertIsInstance(entry.volume_value, Decimal)
        self.assertTrue(entry.is_injectable)
        self.assertTrue(entry.is_high_alert)
        self.assertTrue(entry.active)

    def test_is_high_alert_defaults_false(self):
        entry = MedicationFormulary.objects.create(
            drug=self.drug,
            strength_value=Decimal("500.000"),
            strength_unit="mg",
            route=MedicationFormulary.Route.PO,
        )
        self.assertFalse(entry.is_high_alert)
        self.assertFalse(entry.is_injectable)

    def test_dose_checkable_predicate_is_formulary_existence(self):
        """A drug is dose-checkable iff a MedicationFormulary row exists for it."""
        # No formulary yet → not dose-checkable.
        self.assertFalse(hasattr(self.drug, "formulary") and self._formulary_exists(self.drug))

        MedicationFormulary.objects.create(
            drug=self.drug,
            strength_value=Decimal("10.000"),
            strength_unit="mg",
            route=MedicationFormulary.Route.IV,
            is_injectable=True,
        )
        self.assertTrue(self._formulary_exists(self.drug))

        # A different drug with no row stays not-checkable.
        other = Drug.objects.create(name="Uncurated Drug")
        self.assertFalse(self._formulary_exists(other))

    @staticmethod
    def _formulary_exists(drug):
        return MedicationFormulary.objects.filter(drug=drug, active=True).exists()

    def test_one_formulary_per_drug(self):
        MedicationFormulary.objects.create(
            drug=self.drug,
            strength_value=Decimal("10.000"),
            strength_unit="mg",
            route=MedicationFormulary.Route.IV,
        )
        with self.assertRaises(IntegrityError):
            MedicationFormulary.objects.create(
                drug=self.drug,
                strength_value=Decimal("20.000"),
                strength_unit="mg",
                route=MedicationFormulary.Route.IV,
            )

    def test_strength_unit_rejects_non_choice(self):
        """strength_unit is constrained to the shared mass-only DOSE_UNIT_CHOICES."""
        entry = MedicationFormulary(
            drug=self.drug,
            strength_value=Decimal("10.000"),
            strength_unit="milligrams",  # not a valid choice — only "mg" is
            route=MedicationFormulary.Route.IV,
        )
        with self.assertRaises(ValidationError):
            entry.full_clean()


class TestDoseRule(TenantTestCase):
    def setUp(self):
        self.drug = Drug.objects.create(name="Placeholder 100mg")
        self.formulary = MedicationFormulary.objects.create(
            drug=self.drug,
            strength_value=Decimal("100.000"),
            strength_unit="mg",
            route=MedicationFormulary.Route.IV,
            is_injectable=True,
        )

    # ─── persistence ──────────────────────────────────────────────────────────

    def test_per_kg_rule_persists(self):
        # 18y ≈ 6570 days; pediatric band 0d..12y placeholder.
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            age_min_days=0,
            age_max_days=4380,  # ~12y
            weight_min_kg=Decimal("3.000"),
            weight_max_kg=Decimal("40.000"),
            dose_unit="mg",  # absolute mass unit; per-kg implied by basis
            min_per_kg=Decimal("0.1000"),
            max_per_kg=Decimal("0.5000"),
            absolute_max_dose=Decimal("5.0000"),  # universal hard ceiling, placeholder
            max_per_day=Decimal("15.0000"),
            notes="Placeholder — pharmacist source pending (PR B).",
        )
        rule.refresh_from_db()
        self.assertEqual(rule.basis, "per_kg")
        self.assertEqual(rule.dose_unit, "mg")
        self.assertEqual(rule.min_per_kg, Decimal("0.1000"))
        self.assertEqual(rule.max_per_kg, Decimal("0.5000"))
        self.assertIsInstance(rule.max_per_kg, Decimal)
        self.assertEqual(rule.absolute_max_dose, Decimal("5.0000"))
        self.assertEqual(rule.weight_min_kg, Decimal("3.000"))

    def test_fixed_rule_persists(self):
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mEq",
            min_per_dose=Decimal("250.0000"),
            max_per_dose=Decimal("1000.0000"),  # placeholder
            absolute_max_dose=Decimal("2000.0000"),  # placeholder cap
        )
        rule.refresh_from_db()
        self.assertEqual(rule.basis, "fixed")
        self.assertIsNone(rule.age_min_days)
        self.assertIsNone(rule.weight_min_kg)
        self.assertIsNone(rule.min_per_kg)
        self.assertEqual(rule.max_per_dose, Decimal("1000.0000"))
        self.assertEqual(rule.absolute_max_dose, Decimal("2000.0000"))

    def test_age_band_in_days(self):
        """Age bands are stored in DAYS so neonatal/infant rules don't collapse to 0y."""
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            age_min_days=0,
            age_max_days=28,  # neonatal window — impossible to express in years
            dose_unit="mcg",
            min_per_kg=Decimal("1.0000"),
            max_per_kg=Decimal("4.0000"),
            absolute_max_dose=Decimal("50.0000"),
        )
        rule.refresh_from_db()
        self.assertEqual(rule.age_min_days, 0)
        self.assertEqual(rule.age_max_days, 28)

    def test_decimal_precision_no_float_drift(self):
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("0.1000"),
            max_per_dose=Decimal("0.3333"),
            absolute_max_dose=Decimal("0.3333"),
        )
        rule.refresh_from_db()
        # A float 0.3333 would not compare equal to the Decimal; this asserts no coercion.
        self.assertEqual(rule.absolute_max_dose, Decimal("0.3333"))
        self.assertIsInstance(rule.absolute_max_dose, Decimal)

    def test_multiple_rules_per_formulary(self):
        DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            age_min_days=0,
            age_max_days=4380,  # ~12y
            dose_unit="mg",
            min_per_kg=Decimal("0.1000"),
            max_per_kg=Decimal("0.5000"),
            absolute_max_dose=Decimal("5.0000"),
        )
        DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            age_min_days=4380,  # ~12y
            dose_unit="mg",
            min_per_dose=Decimal("250.0000"),
            max_per_dose=Decimal("1000.0000"),
            absolute_max_dose=Decimal("2000.0000"),
        )
        self.assertEqual(self.formulary.dose_rules.count(), 2)

    # ─── absolute_max_dose mandatory (NOT NULL) ────────────────────────────────

    def test_absolute_max_dose_is_required_db_level(self):
        """absolute_max_dose is the mandatory universal ceiling — NOT NULL at the DB."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DoseRule.objects.create(
                    formulary=self.formulary,
                    basis=DoseRule.Basis.FIXED,
                    dose_unit="mg",
                    min_per_dose=Decimal("1.0000"),
                    max_per_dose=Decimal("2.0000"),
                    absolute_max_dose=None,
                )

    def test_clean_requires_absolute_max_dose(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("1.0000"),
            max_per_dose=Decimal("2.0000"),
            absolute_max_dose=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("absolute_max_dose", ctx.exception.message_dict)

    def test_clean_rejects_non_positive_absolute_max_dose(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("1.0000"),
            max_per_dose=Decimal("2.0000"),
            absolute_max_dose=Decimal("0.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("absolute_max_dose", ctx.exception.message_dict)

    # ─── clean() per-basis invariants ──────────────────────────────────────────

    def test_clean_per_kg_rejects_missing_max_per_kg(self):
        """A per_kg rule without the per-kg UPPER bound is the original FATAL hole."""
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            dose_unit="mg",
            min_per_kg=Decimal("0.1000"),
            max_per_kg=None,  # missing per-kg ceiling
            absolute_max_dose=Decimal("5.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("max_per_kg", ctx.exception.message_dict)

    def test_clean_per_kg_rejects_missing_min_per_kg(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            dose_unit="mg",
            min_per_kg=None,
            max_per_kg=Decimal("0.5000"),
            absolute_max_dose=Decimal("5.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("min_per_kg", ctx.exception.message_dict)

    def test_clean_per_kg_rejects_inverted_band(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            dose_unit="mg",
            min_per_kg=Decimal("0.5000"),
            max_per_kg=Decimal("0.1000"),  # max < min
            absolute_max_dose=Decimal("5.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("max_per_kg", ctx.exception.message_dict)

    def test_clean_fixed_rejects_missing_per_dose_band(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=None,
            max_per_dose=None,
            absolute_max_dose=Decimal("5.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("min_per_dose", ctx.exception.message_dict)
        self.assertIn("max_per_dose", ctx.exception.message_dict)

    def test_clean_fixed_rejects_inverted_band(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("1000.0000"),
            max_per_dose=Decimal("250.0000"),  # max < min
            absolute_max_dose=Decimal("2000.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            rule.clean()
        self.assertIn("max_per_dose", ctx.exception.message_dict)

    def test_clean_passes_for_valid_per_kg_rule(self):
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            dose_unit="mg",
            min_per_kg=Decimal("0.1000"),
            max_per_kg=Decimal("0.5000"),
            absolute_max_dose=Decimal("5.0000"),
        )
        rule.clean()  # must not raise

    # ─── unit choices ──────────────────────────────────────────────────────────

    def test_dose_unit_rejects_non_choice(self):
        """dose_unit is constrained to the shared mass-only DOSE_UNIT_CHOICES (no 'mg/kg')."""
        rule = DoseRule(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            dose_unit="mg/kg",  # the killed unit paradox — not a valid choice
            min_per_kg=Decimal("0.1000"),
            max_per_kg=Decimal("0.5000"),
            absolute_max_dose=Decimal("5.0000"),
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()
