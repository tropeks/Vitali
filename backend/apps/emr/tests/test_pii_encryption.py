"""LGPD: sensitive patient PII and clinical free-text are encrypted at rest.

Verifies that the encrypted columns hold ciphertext in the database, that
values round-trip transparently (including the JSON address), that name search
still works in Python now that full_name is encrypted, and that the data
migration re-encrypts pre-existing plaintext rows.
"""

import datetime
import importlib

from django.db import connection

from apps.emr.filters import PatientFilter, PatientSearchFilter
from apps.emr.models import (
    ClinicalDocument,
    Encounter,
    MedicalHistory,
    Patient,
    Professional,
    SOAPNote,
)
from apps.test_utils import TenantTestCase


def _make_patient(**kwargs):
    defaults = {
        "full_name": "Ana Maria Souza",
        "cpf": "123.456.789-09",
        "birth_date": datetime.date(1990, 5, 20),
        "gender": "F",
        "phone": "+5511988887777",
        "email": "ana.souza@example.com",
        "address": {"city": "São Paulo", "state": "SP", "line": ["Rua das Flores, 100"]},
        "notes": "Paciente com histórico de hipertensão.",
    }
    defaults.update(kwargs)
    return Patient.objects.create(**defaults)


class TestPatientPIIEncryption(TenantTestCase):
    def test_pii_columns_stored_as_ciphertext(self):
        patient = _make_patient()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT full_name, email, phone, address, notes FROM emr_patient WHERE id = %s",
                [str(patient.pk)],
            )
            full_name, email, phone, address, notes = cursor.fetchone()

        # None of the plaintext should be present in the raw DB columns.
        self.assertNotIn("Ana Maria Souza", full_name)
        self.assertNotIn("ana.souza@example.com", email)
        self.assertNotIn("988887777", phone)
        self.assertNotIn("São Paulo", address)
        self.assertNotIn("hipertensão", notes)
        # Fernet ciphertext is URL-safe base64 starting with the version byte.
        self.assertTrue(full_name.startswith("gAAAAA"))

    def test_pii_round_trips_including_json_address(self):
        patient = _make_patient()
        refreshed = Patient.objects.get(pk=patient.pk)
        self.assertEqual(refreshed.full_name, "Ana Maria Souza")
        self.assertEqual(refreshed.email, "ana.souza@example.com")
        self.assertEqual(refreshed.phone, "+5511988887777")
        self.assertEqual(refreshed.notes, "Paciente com histórico de hipertensão.")
        # address stays a native dict, not a string.
        self.assertIsInstance(refreshed.address, dict)
        self.assertEqual(refreshed.address["city"], "São Paulo")
        self.assertEqual(refreshed.address["line"], ["Rua das Flores, 100"])

    def test_address_default_empty_dict(self):
        patient = _make_patient(address={})
        self.assertEqual(Patient.objects.get(pk=patient.pk).address, {})


class TestClinicalFreeTextEncryption(TenantTestCase):
    def setUp(self):
        from apps.core.models import User

        self.patient = _make_patient(cpf="987.654.321-00", full_name="Bruno Lima")
        user = User.objects.create_user(email="doc_pii@clinic.test", password="pw")
        self.professional = Professional.objects.create(
            user=user, council_type="CRM", council_number="9911", council_state="SP"
        )

    def test_encounter_and_soap_and_document_encrypted(self):
        encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            chief_complaint="Dor torácica há 2 dias",
        )
        SOAPNote.objects.create(
            encounter=encounter,
            assessment="Hipótese: angina instável (CID I20.0)",
            plan="Solicitar ECG e troponina",
        )
        doc = ClinicalDocument.objects.create(
            encounter=encounter,
            doc_type="report",
            content="Laudo: paciente apresenta sinais de isquemia.",
        )
        history = MedicalHistory.objects.create(
            patient=self.patient,
            condition="Hipertensão",
            type="chronic",
            notes="Em uso de losartana 50mg.",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT chief_complaint FROM emr_encounter WHERE id = %s", [str(encounter.pk)]
            )
            raw_complaint = cursor.fetchone()[0]
            cursor.execute(
                "SELECT assessment, plan FROM emr_soapnote WHERE encounter_id = %s",
                [str(encounter.pk)],
            )
            raw_assessment, raw_plan = cursor.fetchone()
            cursor.execute("SELECT content FROM emr_clinicaldocument WHERE id = %s", [str(doc.pk)])
            raw_content = cursor.fetchone()[0]
            cursor.execute("SELECT notes FROM emr_medicalhistory WHERE id = %s", [str(history.pk)])
            raw_history_notes = cursor.fetchone()[0]

        self.assertNotIn("angina", raw_assessment)
        self.assertNotIn("torácica", raw_complaint)
        self.assertNotIn("ECG", raw_plan)
        self.assertNotIn("isquemia", raw_content)
        self.assertNotIn("losartana", raw_history_notes)

        # round-trips
        self.assertEqual(
            SOAPNote.objects.get(encounter=encounter).assessment,
            "Hipótese: angina instável (CID I20.0)",
        )
        self.assertEqual(
            ClinicalDocument.objects.get(pk=doc.pk).content,
            "Laudo: paciente apresenta sinais de isquemia.",
        )


class TestEncryptedNameSearch(TenantTestCase):
    """full_name is encrypted → SQL LIKE no longer matches; search/filter must
    fall back to Python decryption."""

    def setUp(self):
        self.ana = _make_patient(full_name="Ana Maria Souza", cpf="111.111.111-11")
        self.bruno = _make_patient(
            full_name="Bruno Lima",
            cpf="222.222.222-22",
            social_name="Bru",
            phone="+5511977776666",
            email="bruno.lima@example.com",
        )

    def _request(self, params):
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        # Wrap in a DRF Request so `.query_params` is available (as in prod).
        return Request(APIRequestFactory().get("/api/patients/", params))

    def test_search_filter_finds_by_partial_name(self):
        qs = Patient.objects.all()
        result = PatientSearchFilter().filter_queryset(
            self._request({"search": "maria"}), qs, view=None
        )
        ids = list(result.values_list("id", flat=True))
        self.assertIn(self.ana.id, ids)
        self.assertNotIn(self.bruno.id, ids)

    def test_search_filter_matches_plaintext_mrn(self):
        qs = Patient.objects.all()
        result = PatientSearchFilter().filter_queryset(
            self._request({"search": self.bruno.medical_record_number}), qs, view=None
        )
        ids = list(result.values_list("id", flat=True))
        self.assertEqual(ids, [self.bruno.id])

    def test_search_filter_matches_complete_cpf_with_or_without_mask(self):
        qs = Patient.objects.all()
        for term in ("111.111.111-11", "11111111111"):
            with self.subTest(term=term):
                result = PatientSearchFilter().filter_queryset(
                    self._request({"search": term}), qs, view=None
                )
                self.assertEqual(list(result.values_list("id", flat=True)), [self.ana.id])

        partial = PatientSearchFilter().filter_queryset(
            self._request({"search": "111111"}), qs, view=None
        )
        self.assertNotIn(self.ana.id, partial.values_list("id", flat=True))

    def test_search_filter_matches_encrypted_contact_without_exposing_it(self):
        result = PatientSearchFilter().filter_queryset(
            self._request({"search": "988887777"}), Patient.objects.all(), view=None
        )
        self.assertEqual(list(result.values_list("id", flat=True)), [self.ana.id])

        result = PatientSearchFilter().filter_queryset(
            self._request({"search": "ana.souza@example"}), Patient.objects.all(), view=None
        )
        self.assertEqual(list(result.values_list("id", flat=True)), [self.ana.id])

    def test_search_filter_matches_complete_cns_and_identity_document(self):
        self.bruno.cns = "123456789012345"
        self.bruno.identity_document = "MG-12.345.678"
        self.bruno.save(update_fields=["cns", "identity_document"])

        for term in ("123456789012345", "MG 12.345.678"):
            with self.subTest(term=term):
                result = PatientSearchFilter().filter_queryset(
                    self._request({"search": term}), Patient.objects.all(), view=None
                )
                self.assertEqual(list(result.values_list("id", flat=True)), [self.bruno.id])

    def test_search_openapi_description_lists_supported_identifiers(self):
        [parameter] = PatientSearchFilter().get_schema_operation_parameters(view=None)
        self.assertIn("CPF completo", parameter["description"])
        self.assertIn("CNS completo", parameter["description"])
        self.assertIn("e-mail", parameter["description"])

    def test_name_filter_finds_by_social_name(self):
        f = PatientFilter(data={"name": "bru"}, queryset=Patient.objects.all())
        self.assertTrue(f.is_valid())
        ids = list(f.qs.values_list("id", flat=True))
        self.assertEqual(ids, [self.bruno.id])


class TestMigrationReEncryptsPlaintext(TenantTestCase):
    def test_encrypt_existing_pii_encrypts_legacy_rows(self):
        patient = _make_patient(full_name="Carla Dias", cpf="333.333.333-33")

        # Simulate a legacy plaintext row by overwriting the column directly.
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE emr_patient SET full_name = %s WHERE id = %s",
                ["Carla Dias", str(patient.pk)],
            )
            cursor.execute("SELECT full_name FROM emr_patient WHERE id = %s", [str(patient.pk)])
            self.assertEqual(cursor.fetchone()[0], "Carla Dias")  # plaintext present

        # The model still reads it (decrypt fails → plaintext fallback).
        self.assertEqual(Patient.objects.get(pk=patient.pk).full_name, "Carla Dias")

        migration = importlib.import_module("apps.emr.migrations.0016_encrypt_patient_pii")
        migration.encrypt_existing_pii(apps=None, schema_editor=None)

        with connection.cursor() as cursor:
            cursor.execute("SELECT full_name FROM emr_patient WHERE id = %s", [str(patient.pk)])
            raw = cursor.fetchone()[0]
        self.assertNotEqual(raw, "Carla Dias")
        self.assertTrue(raw.startswith("gAAAAA"))
        self.assertEqual(Patient.objects.get(pk=patient.pk).full_name, "Carla Dias")
