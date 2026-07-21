"""Safety checks for the tenant starter laboratory catalog."""

from django.test import SimpleTestCase

from apps.emr.management.commands.seed_lab_catalog import PANEL_COMPONENTS, STARTER_TESTS
from apps.emr.models import LabTest


class StarterLabCatalogTest(SimpleTestCase):
    def test_catalog_codes_are_unique_and_cover_supported_categories(self):
        codes = [test[0] for test in STARTER_TESTS]
        categories = {test[2] for test in STARTER_TESTS}

        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(
            categories,
            {
                LabTest.Category.HEMATOLOGY,
                LabTest.Category.BIOCHEMISTRY,
                LabTest.Category.IMMUNOLOGY,
                LabTest.Category.HORMONES,
                LabTest.Category.MICROBIOLOGY,
                LabTest.Category.URINALYSIS,
                LabTest.Category.PARASITOLOGY,
                LabTest.Category.COAGULATION,
                LabTest.Category.TOXICOLOGY,
                LabTest.Category.MOLECULAR,
                LabTest.Category.PATHOLOGY,
                LabTest.Category.RAPID_TEST,
            },
        )

    def test_catalog_uses_only_declared_result_types(self):
        result_types = {choice for choice, _ in LabTest.ResultType.choices}

        for code, name, category, result_type, specimen_type, unit in STARTER_TESTS:
            with self.subTest(code=code):
                self.assertTrue(code)
                self.assertTrue(name)
                self.assertTrue(specimen_type)
                self.assertIn(category, dict(LabTest.Category.choices))
                self.assertIn(result_type, result_types)
                self.assertLessEqual(len(unit), 32)

    def test_panel_components_have_unique_local_codes_without_reference_ranges(self):
        catalog_codes = {test[0] for test in STARTER_TESTS}
        panel_codes = {test[0] for test in STARTER_TESTS if test[3] == LabTest.ResultType.PANEL}

        self.assertLessEqual(PANEL_COMPONENTS.keys(), panel_codes)
        self.assertLessEqual(PANEL_COMPONENTS.keys(), catalog_codes)
        for test_code, components in PANEL_COMPONENTS.items():
            component_codes = [component["code"] for component in components]
            with self.subTest(code=test_code):
                self.assertEqual(len(component_codes), len(set(component_codes)))
                self.assertTrue(all(component.get("name") for component in components))
                self.assertTrue(all("reference_range" not in component for component in components))
