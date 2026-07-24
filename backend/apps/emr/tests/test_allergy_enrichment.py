"""E2-T2 — Allergy enriched with a governed AllergenClass FK + coded fields.

Covers: the FK can be set/read; the coded reaction/criticality/verification
fields; and the reconcile helper used by the data migration best-effort maps
existing free-text ``substance`` to an AllergenClass (matched → FK, unmatched →
kept + flagged, NEVER lost).
"""

from apps.emr.allergen_backfill import reconcile_allergies
from apps.emr.models import Allergy, Patient
from apps.pharmacy.models import AllergenClass
from apps.test_utils import TenantTestCase


def _patient(cpf="77777777777"):
    return Patient.objects.create(
        full_name="Allergy Patient", birth_date="1980-01-01", gender="M", cpf=cpf
    )


class TestAllergyFK(TenantTestCase):
    def test_allergen_class_fk_set_and_read(self):
        cls = AllergenClass.objects.create(
            name="Beta-lactâmicos", members=["penicilina", "amoxicilina"]
        )
        a = Allergy.objects.create(
            patient=_patient(),
            substance="penicilina",
            severity="severe",
            allergen_class=cls,
            reaction_type=Allergy.ReactionType.ANAPHYLAXIS,
            criticality=Allergy.Criticality.HIGH,
            verification_status=Allergy.VerificationStatus.CONFIRMED,
        )
        a.refresh_from_db()
        self.assertEqual(a.allergen_class_id, cls.id)
        self.assertEqual(a.reaction_type, "anaphylaxis")
        self.assertEqual(a.criticality, "high")
        self.assertEqual(a.verification_status, "confirmed")

    def test_fk_nullable_during_transition(self):
        a = Allergy.objects.create(patient=_patient(), substance="camarão", severity="moderate")
        self.assertIsNone(a.allergen_class_id)
        self.assertEqual(a.verification_status, "unconfirmed")


class TestAllergyReconcile(TenantTestCase):
    def test_reconcile_maps_matched_and_preserves_unmatched(self):
        AllergenClass.objects.create(
            name="Beta-lactâmicos", members=["penicilina", "amoxicilina", "ampicilina"]
        )
        matched = Allergy.objects.create(
            patient=_patient(), substance="amoxicilina 500mg", severity="severe"
        )
        by_name = Allergy.objects.create(
            patient=_patient(cpf="77777777778"),
            substance="Beta-lactâmicos",
            severity="mild",
        )
        unmatched = Allergy.objects.create(
            patient=_patient(cpf="77777777779"), substance="poeira", severity="mild"
        )

        linked, unmatched_count = reconcile_allergies(Allergy, AllergenClass)
        self.assertEqual((linked, unmatched_count), (2, 1))

        matched.refresh_from_db()
        by_name.refresh_from_db()
        unmatched.refresh_from_db()
        self.assertIsNotNone(matched.allergen_class_id)
        self.assertFalse(matched.allergen_unmatched)
        self.assertEqual(matched.substance, "amoxicilina 500mg")  # never lost
        self.assertIsNotNone(by_name.allergen_class_id)
        # Unmatched: substance preserved, flagged.
        self.assertIsNone(unmatched.allergen_class_id)
        self.assertTrue(unmatched.allergen_unmatched)
        self.assertEqual(unmatched.substance, "poeira")

    def test_reconcile_is_idempotent_and_skips_linked(self):
        cls = AllergenClass.objects.create(name="Penicilinas", members=["penicilina"])
        Allergy.objects.create(
            patient=_patient(),
            substance="penicilina",
            severity="severe",
            allergen_class=cls,
        )
        linked, unmatched = reconcile_allergies(Allergy, AllergenClass)
        # Already linked → not re-counted.
        self.assertEqual((linked, unmatched), (0, 0))
