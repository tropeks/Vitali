from datetime import UTC, date, datetime

from rest_framework.test import APIClient

from apps.core.imaging_bridge import DicomStudy
from apps.core.models import FeatureFlag, Role, User
from apps.emr.models import ClinicalDocument, Encounter, Patient, Professional
from apps.patient_portal.models import PatientPortalAccess
from apps.test_utils import TenantTestCase


class PortalImagingTest(TenantTestCase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="patient_portal",
            defaults={"is_enabled": True},
        )
        role = Role.objects.create(name="portal_imaging", permissions=["portal.self_access"])
        self.user = User.objects.create_user(
            email="patient-image@test.com", password="pw", role=role
        )
        clinician = User.objects.create_user(
            email="signer-image@test.com", password="pw", full_name="Dra. Laudo"
        )
        professional = Professional.objects.create(
            user=clinician, council_type="CRM", council_number="100", council_state="SP"
        )
        self.patient = Patient.objects.create(
            full_name="Paciente", birth_date=date(1990, 1, 1), gender="F", cpf="54444444444"
        )
        self.other = Patient.objects.create(
            full_name="Outro", birth_date=date(1991, 1, 1), gender="M", cpf="55555555555"
        )
        access = PatientPortalAccess.objects.create(user=self.user, patient=self.patient)
        access.status = PatientPortalAccess.STATUS_ACTIVE
        access.save(update_fields=["status"])
        encounter = Encounter.objects.create(
            patient=self.patient,
            professional=professional,
            status="signed",
            encounter_date=datetime(2026, 7, 20, tzinfo=UTC),
        )
        report = ClinicalDocument.objects.create(
            encounter=encounter, doc_type="report", content="Laudo do próprio paciente."
        )
        report.sign(clinician, is_icp_brasil=True, signature_hash="abc123")
        self.own = self._study(self.patient, "1.2.3.own", report=report, pixels=True)
        self.other_study = self._study(self.other, "1.2.3.other", pixels=True)
        self.unsigned = ClinicalDocument.objects.create(
            encounter=encounter, doc_type="report", content="Rascunho não liberado."
        )
        self.draft_study = self._study(self.patient, "1.2.3.draft", report=self.unsigned)
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.user)

    def _study(self, patient, uid, *, report=None, pixels=False):
        return DicomStudy.objects.create(
            patient=patient,
            report_document=report,
            study_instance_uid=uid,
            accession_number=uid.rsplit(".", 1)[-1],
            modality="CT",
            study_date=datetime(2026, 7, 20, tzinfo=UTC),
            number_of_series=2,
            number_of_instances=10,
            orthanc_study_id="stored-study" if pixels else "",
        )

    def test_list_contains_only_own_studies_and_patient_safe_fields(self):
        response = self.client.get("/api/v1/portal/me/imaging-studies/")
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.own.id), str(self.draft_study.id)})
        own = next(row for row in response.data if row["id"] == str(self.own.id))
        self.assertEqual(own["series_count"], 2)
        self.assertTrue(own["available"])
        self.assertNotIn("orthanc_study_id", own)
        self.assertIsNotNone(own["report_url"])
        draft = next(row for row in response.data if row["id"] == str(self.draft_study.id))
        self.assertIsNone(draft["report_url"])

    def test_report_and_viewer_authorization_are_anti_idor_scoped(self):
        own_report = self.client.get(f"/api/v1/portal/me/imaging-studies/{self.own.id}/report/")
        self.assertEqual(own_report.status_code, 200)
        self.assertEqual(own_report.data["content"], "Laudo do próprio paciente.")
        self.assertEqual(
            self.client.get(
                f"/api/v1/portal/me/imaging-studies/{self.other_study.id}/report/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/portal/me/imaging-studies/{self.unsigned.id}/report/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/portal/me/imaging-studies/{self.own.id}/authorize/"
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/portal/me/imaging-studies/{self.other_study.id}/authorize/"
            ).status_code,
            404,
        )

    def test_revoked_portal_access_is_denied(self):
        access = self.user.patient_portal_access
        access.revoke()
        self.assertEqual(self.client.get("/api/v1/portal/me/imaging-studies/").status_code, 403)

    def test_viewer_proxy_auth_scopes_every_patient_data_request(self):
        url = "/api/v1/portal/me/imaging-viewer-auth/"
        self.assertEqual(
            self.client.get(url, HTTP_X_ORIGINAL_URI="/visualizador/app.bundle.js").status_code, 204
        )
        self.assertEqual(
            self.client.get(
                url,
                HTTP_X_ORIGINAL_URI=f"/visualizador/viewer?StudyInstanceUIDs={self.own.study_instance_uid}",
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(
                url,
                HTTP_X_ORIGINAL_URI=(
                    f"/imagens-dicom/studies/{self.own.study_instance_uid}/series/1/instances/1"
                ),
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(url, HTTP_X_ORIGINAL_URI="/imagens-dicom/studies").status_code, 403
        )
        self.assertEqual(
            self.client.get(
                url,
                HTTP_X_ORIGINAL_URI=(
                    "/imagens-dicom/studies?"
                    f"StudyInstanceUID={self.own.study_instance_uid}&"
                    f"StudyInstanceUID={self.other_study.study_instance_uid}"
                ),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                url,
                HTTP_X_ORIGINAL_URI=(
                    f"/imagens-dicom/studies?StudyInstanceUID={self.other_study.study_instance_uid}"
                ),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(url, HTTP_X_ORIGINAL_URI="/api/v1/users/").status_code, 403
        )
