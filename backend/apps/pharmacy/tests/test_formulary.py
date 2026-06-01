"""
Dose-safety wedge PR A — MedicationFormulary & DoseRule schema tests.

PURE SCHEMA. No clinical dose numbers are asserted as correct here — the
placeholder figures below exist only to exercise persistence and Decimal
precision. The curated formulary + real dose bands are pharmacist-supplied
external truth that lands with the deterministic engine in PR B.

Covered:
  - MedicationFormulary / DoseRule create + Decimal precision (no float drift)
  - "is this drug dose-checkable?" predicate = formulary row exists
  - DoseRule basis="per_kg" AND basis="fixed" both persist
  - max_per_dose is mandatory (NOT NULL)
"""

from decimal import Decimal

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

    def test_per_kg_rule_persists(self):
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            age_min_years=0,
            age_max_years=12,
            weight_min_kg=Decimal("3.000"),
            weight_max_kg=Decimal("40.000"),
            dose_unit="mg/kg",
            min_per_dose=Decimal("0.1000"),
            max_per_dose=Decimal("5.0000"),  # absolute ceiling, placeholder
            max_per_day=Decimal("15.0000"),
            notes="Placeholder — pharmacist source pending (PR B).",
        )
        rule.refresh_from_db()
        self.assertEqual(rule.basis, "per_kg")
        self.assertEqual(rule.max_per_dose, Decimal("5.0000"))
        self.assertIsInstance(rule.max_per_dose, Decimal)
        self.assertEqual(rule.weight_min_kg, Decimal("3.000"))

    def test_fixed_rule_persists(self):
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            min_per_dose=Decimal("250.0000"),
            max_per_dose=Decimal("1000.0000"),  # placeholder
        )
        rule.refresh_from_db()
        self.assertEqual(rule.basis, "fixed")
        self.assertIsNone(rule.age_min_years)
        self.assertIsNone(rule.weight_min_kg)
        self.assertEqual(rule.max_per_dose, Decimal("1000.0000"))

    def test_max_per_dose_is_required(self):
        """max_per_dose is the mandatory absolute ceiling — NOT NULL."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DoseRule.objects.create(
                    formulary=self.formulary,
                    basis=DoseRule.Basis.FIXED,
                    dose_unit="mg",
                    max_per_dose=None,
                )

    def test_decimal_precision_no_float_drift(self):
        rule = DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            dose_unit="mg",
            max_per_dose=Decimal("0.3333"),
        )
        rule.refresh_from_db()
        # A float 0.3333 would not compare equal to the Decimal; this asserts no coercion.
        self.assertEqual(rule.max_per_dose, Decimal("0.3333"))
        self.assertIsInstance(rule.max_per_dose, Decimal)

    def test_multiple_rules_per_formulary(self):
        DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.PER_KG,
            age_min_years=0,
            age_max_years=11,
            dose_unit="mg/kg",
            max_per_dose=Decimal("5.0000"),
        )
        DoseRule.objects.create(
            formulary=self.formulary,
            basis=DoseRule.Basis.FIXED,
            age_min_years=12,
            dose_unit="mg",
            max_per_dose=Decimal("1000.0000"),
        )
        self.assertEqual(self.formulary.dose_rules.count(), 2)
