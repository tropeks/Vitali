"""
E1-T2 — CID-10 rich, hierarchical, versioned catalog.

CID10Code lives in the PUBLIC/SHARED schema (real migrated table), so a plain
TenantTestCase suffices — no schema_editor gymnastics.
"""

from apps.core.models import CID10Code
from apps.test_utils import TenantTestCase


class TestCID10RichFields(TenantTestCase):
    def test_new_fields_have_safe_inert_defaults(self):
        code = CID10Code.objects.create(code="A00", description="Cólera")
        code.refresh_from_db()
        self.assertEqual(code.version, "")
        self.assertEqual(code.sex_allowed, "B")
        self.assertIsNone(code.age_min)
        self.assertIsNone(code.age_max)
        self.assertFalse(code.is_notifiable)
        self.assertIsNone(code.parent)
        self.assertEqual(code.chapter, "")
        self.assertEqual(code.group, "")
        self.assertEqual(code.category, "")

    def test_description_still_readable_and_writable(self):
        code = CID10Code.objects.create(code="E10", description="Diabetes tipo 1")
        code.refresh_from_db()
        self.assertEqual(code.description, "Diabetes tipo 1")

    def test_normalized_description_synced_on_save(self):
        code = CID10Code.objects.create(code="I10", description="Hipertensão Essencial")
        code.refresh_from_db()
        self.assertEqual(code.normalized_description, "hipertensao essencial")
        # Re-sync on change
        code.description = "Coração"
        code.save()
        code.refresh_from_db()
        self.assertEqual(code.normalized_description, "coracao")


class TestCID10Hierarchy(TenantTestCase):
    def test_parent_children_relationship(self):
        parent = CID10Code.objects.create(code="A00", description="Cólera", category="A00-A09")
        child = CID10Code.objects.create(
            code="A000", description="Cólera devida a Vibrio cholerae", parent=parent
        )
        child.refresh_from_db()
        self.assertEqual(child.parent_id, parent.id)
        self.assertIn(child, parent.children.all())

    def test_parent_deletion_sets_null(self):
        parent = CID10Code.objects.create(code="A00", description="Cólera")
        child = CID10Code.objects.create(code="A000", description="sub", parent=parent)
        parent.delete()
        child.refresh_from_db()
        self.assertIsNone(child.parent)


class TestCID10AppliesTo(TenantTestCase):
    def test_sex_constraint(self):
        female_only = CID10Code.objects.create(
            code="O00", description="Gravidez ectópica", sex_allowed="F"
        )
        self.assertTrue(female_only.applies_to(sex="F"))
        self.assertFalse(female_only.applies_to(sex="M"))
        # No sex supplied → not filtered out
        self.assertTrue(female_only.applies_to())

    def test_sex_both_always_applies(self):
        any_sex = CID10Code.objects.create(code="J00", description="Resfriado", sex_allowed="B")
        self.assertTrue(any_sex.applies_to(sex="M"))
        self.assertTrue(any_sex.applies_to(sex="F"))

    def test_age_window(self):
        pediatric = CID10Code.objects.create(
            code="P00", description="Afecção perinatal", age_min=0, age_max=28
        )
        self.assertTrue(pediatric.applies_to(age_days=10))
        self.assertFalse(pediatric.applies_to(age_days=100))
        # No age supplied → not filtered out
        self.assertTrue(pediatric.applies_to())

    def test_combined_sex_and_age(self):
        code = CID10Code.objects.create(
            code="N70", description="Salpingite", sex_allowed="F", age_min=3650, age_max=None
        )
        self.assertTrue(code.applies_to(sex="F", age_days=5000))
        self.assertFalse(code.applies_to(sex="M", age_days=5000))
        self.assertFalse(code.applies_to(sex="F", age_days=100))

    def test_unbounded_age_window(self):
        code = CID10Code.objects.create(code="R51", description="Cefaleia")
        self.assertTrue(code.applies_to(age_days=0))
        self.assertTrue(code.applies_to(age_days=40000))
