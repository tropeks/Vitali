"""Fail-closed contract tests for Vitali ↔ PACS patient identity links."""

from datetime import UTC, date, datetime
from unittest.mock import patch

from apps.emr.models import Patient
from apps.imaging.models import DicomStudy
from apps.imaging.services import orthanc_sync
from apps.imaging.services.orthanc_client import OrthancClient
from apps.test_utils import TenantTestCase


class DicomIdentityIntegrityTest(TenantTestCase):
    def setUp(self):
        self.patient = Patient.objects.create(
            full_name="Paciente A",
            cpf="12345678909",
            birth_date=date(1990, 1, 1),
            gender="F",
        )
        self.study = self._study(
            patient=self.patient,
            uid="1.2.826.0.1.3680043.10.999.1",
            accession="ACC-IDENTITY-1",
        )

    def _study(self, *, patient, uid, accession):
        return DicomStudy.objects.create(
            patient=patient,
            study_instance_uid=uid,
            accession_number=accession,
            dicom_patient_id=patient.medical_record_number,
            dicom_patient_id_issuer="VITALI",
            modality="CT",
            study_date=datetime(2026, 7, 21, tzinfo=UTC),
        )

    def _apply(self, **overrides):
        values = {
            "orthanc_id": "orth-study-1",
            "study_uid": self.study.study_instance_uid,
            "accession": self.study.accession_number,
            "patient_id": self.patient.medical_record_number,
            "patient_id_issuer": "VITALI",
            "n_series": 2,
            "n_instances": 10,
        }
        values.update(overrides)
        return orthanc_sync._apply_study_to_tenants(**values)

    def test_patient_id_mismatch_is_fail_closed(self):
        self.assertEqual(self._apply(patient_id="PAC-FOREIGN"), "identity_mismatch")
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "")
        self.assertFalse(self.study.dicom_identity_verified)

    def test_missing_patient_id_and_issuer_mismatch_are_fail_closed(self):
        for identity in (
            {"patient_id": ""},
            {"patient_id_issuer": "OTHER-ISSUER"},
        ):
            with self.subTest(identity=identity):
                self.assertEqual(self._apply(**identity), "identity_mismatch")
                self.study.refresh_from_db()
                self.assertEqual(self.study.orthanc_study_id, "")
                self.assertFalse(self.study.dicom_identity_verified)

    def test_duplicate_accession_inside_tenant_is_ambiguous(self):
        second_patient = Patient.objects.create(
            full_name="Paciente B",
            cpf="98765432100",
            birth_date=date(1991, 1, 1),
            gender="M",
        )
        second = self._study(
            patient=second_patient,
            uid="1.2.826.0.1.3680043.10.999.2",
            accession=self.study.accession_number,
        )

        outcome = self._apply(study_uid="9.9.9.unknown")

        self.assertEqual(outcome, "ambiguous")
        for candidate in (self.study, second):
            candidate.refresh_from_db()
            self.assertEqual(candidate.orthanc_study_id, "")
            self.assertFalse(candidate.dicom_identity_verified)

    def test_uid_collision_across_tenants_refuses_every_candidate(self):
        """Even corrupted cross-schema duplicate UIDs must not use first-wins."""

        def duplicate_tenant_scan(callback, *, logger, operation):
            # Running the callback twice models the same UID resolving in two
            # tenant schemas; no apply pass may choose either candidate.
            return [callback("tenant_a"), callback("tenant_b")]

        with patch(
            "apps.imaging.services.orthanc_sync.for_each_tenant_schema",
            side_effect=duplicate_tenant_scan,
        ):
            outcome = self._apply()

        self.assertEqual(outcome, "ambiguous")
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "")
        self.assertFalse(self.study.dicom_identity_verified)

    def test_verified_identity_is_the_only_path_that_marks_pixels_available(self):
        self.study.orthanc_study_id = "legacy-unverified-link"
        self.study.save(update_fields=["orthanc_study_id"])
        self.assertFalse(self.study.has_pixel_data)

        self.assertEqual(self._apply(), "matched")
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "orth-study-1")
        self.assertTrue(self.study.dicom_identity_verified)
        self.assertTrue(self.study.has_pixel_data)

    def test_manual_link_target_cannot_mutate_a_different_valid_study(self):
        """A PATCH for row A must not have a side effect on matching row B."""
        other_patient = Patient.objects.create(
            full_name="Paciente estrangeiro",
            cpf="98765432100",
            birth_date=date(1988, 2, 2),
            gender="M",
        )
        foreign = self._study(
            patient=other_patient,
            uid="1.2.826.0.1.3680043.10.999.foreign",
            accession="ACC-FOREIGN",
        )

        class ForeignStudyClient(OrthancClient):
            def get_study(self, orthanc_id):
                return {
                    "MainDicomTags": {
                        "StudyInstanceUID": foreign.study_instance_uid,
                        "AccessionNumber": foreign.accession_number,
                    },
                    "PatientMainDicomTags": {
                        "PatientID": foreign.dicom_patient_id,
                        "IssuerOfPatientID": foreign.dicom_patient_id_issuer,
                    },
                    "Series": ["series-1"],
                }

            def get_study_statistics(self, orthanc_id):
                return {"CountSeries": 1, "CountInstances": 1}

        outcome = orthanc_sync.verify_and_link_study(
            self.study, "orth-foreign", client=ForeignStudyClient()
        )

        self.assertEqual(outcome, "identity_mismatch")
        for candidate in (self.study, foreign):
            candidate.refresh_from_db()
            self.assertEqual(candidate.orthanc_study_id, "")
            self.assertFalse(candidate.dicom_identity_verified)
