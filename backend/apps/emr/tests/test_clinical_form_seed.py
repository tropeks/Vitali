"""E4-T2: seeded anchor specialty template (Clínica Geral anamnese) + API render
into the encounter flow.

The template is seeded by a data migration (0035_seed_anamnesis_template) that
runs per-tenant like every other emr data migration (emr is a TENANT_APP), so
it already exists by the time a TenantTestCase's schema is set up — no
fixture loading needed in the test itself.
"""

from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import ClinicalFormTemplate, Encounter, Patient, Professional
from apps.test_utils import TenantTestCase


class SeededAnamnesisTemplateTests(TenantTestCase):
    def test_anchor_template_seeded_and_published(self):
        template = ClinicalFormTemplate.objects.get(
            name="Anamnese — Clínica Geral", specialty="clinica_geral", version=1
        )
        self.assertTrue(template.is_published)
        self.assertTrue(template.active)
        keys = {field["key"] for field in template.schema}
        self.assertIn("chief_complaint", keys)
        self.assertIn("smoker", keys)


class ClinicalFormAPITests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.role = Role.objects.create(
            name="clinical_forms_test", permissions=["emr.read", "emr.write"]
        )
        self.user = User.objects.create_user(
            email="doc-forms-api@test.local", password="pw", role=self.role
        )
        self.professional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="777", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Fernanda Alves", cpf="99988877766", birth_date="1988-03-10", gender="F"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.template = ClinicalFormTemplate.objects.get(
            name="Anamnese — Clínica Geral", specialty="clinica_geral", version=1
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.user)

    def test_fetch_seeded_template_via_api(self):
        response = self.client.get(
            "/api/v1/clinical-form-templates/", {"specialty": "clinica_geral"}
        )
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        names = [item["name"] for item in results]
        self.assertIn("Anamnese — Clínica Geral", names)

    def test_fill_and_read_back_response_via_api(self):
        answers = {
            "chief_complaint": "Cefaleia há 3 dias",
            "history_of_present_illness": "Dor holocraniana, sem sinais de alarme.",
            "smoker": False,
            "alcohol_use": "social",
            "comorbidities": ["hipertensão"],
        }
        create_response = self.client.post(
            "/api/v1/clinical-form-responses/",
            {
                "template": str(self.template.id),
                "encounter": str(self.encounter.id),
                "answers": answers,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        response_id = create_response.data["id"]
        self.assertEqual(str(create_response.data["patient"]), str(self.patient.id))

        get_response = self.client.get(f"/api/v1/clinical-form-responses/{response_id}/")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.data["answers"], answers)
        self.assertEqual(get_response.data["template_name"], "Anamnese — Clínica Geral")

    def test_invalid_answers_rejected_via_api(self):
        response = self.client.post(
            "/api/v1/clinical-form-responses/",
            {
                "template": str(self.template.id),
                "encounter": str(self.encounter.id),
                "answers": {"smoker": False},  # missing required chief_complaint
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_publishing_seed_template_again_is_a_conflict(self):
        response = self.client.post(f"/api/v1/clinical-form-templates/{self.template.id}/publish/")
        self.assertEqual(response.status_code, 409)

    def test_new_version_of_seed_template_via_api(self):
        response = self.client.post(
            f"/api/v1/clinical-form-templates/{self.template.id}/new-version/",
            {"schema": self.template.schema + [{"key": "x", "label": "X", "type": "text"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["version"], 2)
        self.assertFalse(response.data["is_published"])
