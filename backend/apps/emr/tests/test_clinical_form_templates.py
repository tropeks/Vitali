"""E4-T1: configurable clinical form templates (anamnesis) + validated responses.

A ``ClinicalFormTemplate`` describes a form as a versioned JSON schema.
Publishing freezes it — content changes require a new version. A
``ClinicalFormResponse`` must validate its ``answers`` against the owning
template's schema (required fields present, types/enum respected); invalid
answers are rejected. ``answers`` are PHI and encrypted at rest, same as
``NursingAssessment.content``.
"""

from django.core.exceptions import ValidationError
from django.db import connection

from apps.core.models import User
from apps.emr.models import (
    ClinicalFormResponse,
    ClinicalFormTemplate,
    Encounter,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase

ANAMNESIS_SCHEMA = [
    {"key": "chief_complaint", "label": "Queixa principal", "type": "textarea", "required": True},
    {"key": "onset_days", "label": "Início (dias)", "type": "number", "required": False},
    {"key": "smoker", "label": "Tabagista?", "type": "boolean", "required": True},
    {
        "key": "pain_scale",
        "label": "Escala de dor",
        "type": "select",
        "required": False,
        "options": ["leve", "moderada", "intensa"],
    },
]


def _make_template(**kwargs):
    defaults = {
        "name": "Anamnese Clínica Geral",
        "specialty": "clinica_geral",
        "schema": ANAMNESIS_SCHEMA,
    }
    defaults.update(kwargs)
    return ClinicalFormTemplate.objects.create(**defaults)


class ClinicalFormTemplateSchemaValidationTests(TenantTestCase):
    def test_valid_schema_is_accepted(self):
        template = _make_template()
        self.assertEqual(template.version, 1)
        self.assertFalse(template.is_published)

    def test_schema_must_be_non_empty_list(self):
        with self.assertRaises(ValidationError):
            _make_template(schema=[])

    def test_schema_field_requires_key_and_label(self):
        with self.assertRaises(ValidationError):
            _make_template(schema=[{"label": "Sem key", "type": "text"}])
        with self.assertRaises(ValidationError):
            _make_template(schema=[{"key": "x", "type": "text"}])

    def test_schema_field_type_must_be_known(self):
        with self.assertRaises(ValidationError):
            _make_template(schema=[{"key": "x", "label": "X", "type": "wat"}])

    def test_schema_duplicate_keys_rejected(self):
        with self.assertRaises(ValidationError):
            _make_template(
                schema=[
                    {"key": "x", "label": "X", "type": "text"},
                    {"key": "x", "label": "X2", "type": "text"},
                ]
            )

    def test_select_field_requires_options(self):
        with self.assertRaises(ValidationError):
            _make_template(
                schema=[{"key": "sev", "label": "Severidade", "type": "select", "required": True}]
            )


class ClinicalFormTemplatePublishingTests(TenantTestCase):
    def test_publish_freezes_template(self):
        template = _make_template()
        template.publish()
        self.assertTrue(template.is_published)
        self.assertIsNotNone(template.published_at)

    def test_publishing_twice_rejected(self):
        template = _make_template()
        template.publish()
        with self.assertRaises(ValidationError):
            template.publish()

    def test_editing_published_template_schema_rejected(self):
        template = _make_template()
        template.publish()
        template.schema = ANAMNESIS_SCHEMA + [
            {"key": "extra", "label": "Extra", "type": "text", "required": False}
        ]
        with self.assertRaises(ValidationError):
            template.save()

    def test_active_toggle_stays_editable_after_publish(self):
        template = _make_template()
        template.publish()
        template.active = False
        template.save()
        self.assertFalse(ClinicalFormTemplate.objects.get(pk=template.pk).active)

    def test_new_version_requires_published_source(self):
        template = _make_template()
        with self.assertRaises(ValidationError):
            template.new_version()

    def test_new_version_increments_and_stays_unpublished(self):
        template = _make_template()
        template.publish()
        new_schema = ANAMNESIS_SCHEMA + [
            {"key": "notes", "label": "Notas", "type": "text", "required": False}
        ]
        v2 = template.new_version(schema=new_schema)
        self.assertEqual(v2.version, 2)
        self.assertFalse(v2.is_published)
        self.assertEqual(v2.name, template.name)
        self.assertEqual(v2.specialty, template.specialty)
        # original untouched
        self.assertEqual(ClinicalFormTemplate.objects.get(pk=template.pk).version, 1)


class ClinicalFormResponseValidationTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.template = _make_template()
        self.template.publish()
        self.patient = Patient.objects.create(
            full_name="Carla Nunes", cpf="11122233344", birth_date="1990-01-01", gender="F"
        )
        user = User.objects.create_user(email="doc-forms@test.local", password="pw")
        self.professional = Professional.objects.create(
            user=user, council_type="CRM", council_number="4321", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )

    def _make_response(self, answers):
        return ClinicalFormResponse.objects.create(
            template=self.template,
            encounter=self.encounter,
            answers=answers,
            filled_by=self.professional.user,
        )

    def test_valid_answers_accepted_and_patient_inferred(self):
        response = self._make_response(
            {"chief_complaint": "Dor de cabeça", "smoker": False, "pain_scale": "moderada"}
        )
        self.assertEqual(response.patient_id, self.patient.id)

    def test_missing_required_field_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_response({"smoker": False})

    def test_wrong_type_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_response({"chief_complaint": "Dor", "smoker": "not-a-bool", "onset_days": 3})

    def test_number_field_rejects_string(self):
        with self.assertRaises(ValidationError):
            self._make_response({"chief_complaint": "Dor", "smoker": True, "onset_days": "tres"})

    def test_enum_value_outside_options_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_response({"chief_complaint": "Dor", "smoker": True, "pain_scale": "extrema"})

    def test_undeclared_answer_key_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_response({"chief_complaint": "Dor", "smoker": True, "not_in_schema": "x"})

    def test_answers_round_trip_decrypted(self):
        answers = {"chief_complaint": "Tosse persistente", "smoker": True, "onset_days": 5}
        response = self._make_response(answers)
        refreshed = ClinicalFormResponse.objects.get(pk=response.pk)
        self.assertEqual(refreshed.answers, answers)

    def test_answers_stored_as_ciphertext(self):
        answers = {"chief_complaint": "SINTOMA_SECRETO_XYZ", "smoker": True}
        response = self._make_response(answers)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT answers FROM emr_clinicalformresponse WHERE id = %s", [str(response.pk)]
            )
            (raw,) = cursor.fetchone()
        self.assertNotIn("SINTOMA_SECRETO_XYZ", raw)
        self.assertTrue(raw.startswith("gAAAAA"))

    def test_encounter_patient_mismatch_rejected(self):
        other_patient = Patient.objects.create(
            full_name="Outro Paciente", cpf="55566677788", birth_date="1985-01-01", gender="M"
        )
        with self.assertRaises(ValidationError):
            ClinicalFormResponse.objects.create(
                template=self.template,
                encounter=self.encounter,
                patient=other_patient,
                answers={"chief_complaint": "Dor", "smoker": False},
                filled_by=self.professional.user,
            )
