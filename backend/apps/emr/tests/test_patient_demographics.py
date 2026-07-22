from datetime import date

from django.test import SimpleTestCase
from encrypted_model_fields.fields import EncryptedCharField

from apps.core.fields import EncryptedJSONField
from apps.emr.models import Patient
from apps.emr.serializers import PatientCreateSerializer


class PatientDemographicsContractTests(SimpleTestCase):
    def payload(self, **overrides):
        data = {
            "full_name": "Maria da Silva",
            "cpf": "529.982.247-25",
            "birth_date": date(1990, 5, 20),
            "gender": "F",
            "cns": "123 4567 8901 2345",
            "identity_state": "sp",
            "birth_state": "rj",
            "preferred_language": "pt-br",
            "race_color": "brown",
            "marital_status": "stable_union",
            "accessibility_needs": {"mobility": "wheelchair"},
        }
        data.update(overrides)
        return data

    def test_accepts_and_normalizes_extended_demographics(self):
        serializer = PatientCreateSerializer(data=self.payload())

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["cns"], "123456789012345")
        self.assertEqual(serializer.validated_data["identity_state"], "SP")
        self.assertEqual(serializer.validated_data["birth_state"], "RJ")
        self.assertEqual(serializer.validated_data["preferred_language"], "pt-BR")

    def test_rejects_malformed_cns_and_language(self):
        serializer = PatientCreateSerializer(
            data=self.payload(cns="123", preferred_language="português")
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("cns", serializer.errors)
        self.assertIn("preferred_language", serializer.errors)

    def test_sensitive_demographics_are_encrypted_model_fields(self):
        for field_name in (
            "cns",
            "identity_document",
            "identity_issuer",
            "birth_city",
            "mother_name",
            "father_name",
            "occupation",
        ):
            self.assertIsInstance(Patient._meta.get_field(field_name), EncryptedCharField)
        self.assertIsInstance(Patient._meta.get_field("accessibility_needs"), EncryptedJSONField)

    def test_cns_is_write_only_and_never_returned_in_cleartext(self):
        patient = Patient(**self.payload(cpf="52998224725", cns="123456789012345"))
        representation = PatientCreateSerializer(patient).data

        self.assertNotIn("cns", representation)
        self.assertEqual(representation["cns_masked"], "*** **** **** ****")
