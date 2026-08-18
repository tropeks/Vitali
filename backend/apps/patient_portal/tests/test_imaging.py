from datetime import UTC, date, datetime

from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIClient

from apps.core.imaging_bridge import DicomStudy
from apps.core.models import Domain, FeatureFlag, Role, Tenant, User
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
            dicom_identity_verified=pixels,
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

    def test_unverified_legacy_pacs_link_never_exposes_pixels(self):
        """A stale/wrong FK is not proof that PACS pixels belong to this patient."""
        self.own.dicom_identity_verified = False
        self.own.save(update_fields=["dicom_identity_verified"])

        listing = self.client.get("/api/v1/portal/me/imaging-studies/")
        own = next(row for row in listing.data if row["id"] == str(self.own.id))
        self.assertFalse(own["available"])
        self.assertEqual(
            self.client.get(
                f"/api/v1/portal/me/imaging-studies/{self.own.id}/authorize/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/portal/me/imaging-viewer-auth/",
                HTTP_X_ORIGINAL_URI=(
                    f"/imagens-dicom/studies/{self.own.study_instance_uid}/series/1/instances/1"
                ),
            ).status_code,
            403,
        )


class PortalImagingStaffViewerAuthorizationTest(TenantTestCase):
    """The staff branch of ``MeImagingViewerAuthorizationView`` must be scoped
    to the CURRENT tenant, not just module + RBAC — Orthanc is a single
    archive shared by every clinic (nginx.conf injects the admin credential;
    apps/imaging/services/orthanc_sync.py:11-13 documents the single-instance
    deployment). Module + ``imaging.read`` alone used to authorize ANY URI
    under ``/imagens-dicom/``, which is a cross-tenant PHI-leak vector (QIDO
    catalog + WADO pixels). This mirrors the ownership check the patient
    branch already had, minus the ``patient=`` scoping staff doesn't have.
    """

    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="imaging",
            defaults={"is_enabled": True},
        )
        role = Role.objects.create(name="imaging_staff", permissions=["imaging.read"])
        self.staff = User.objects.create_user(
            email="tech-imaging@test.com", password="pw", role=role
        )
        no_perm_role = Role.objects.create(name="imaging_staff_no_perm", permissions=[])
        self.staff_no_perm = User.objects.create_user(
            email="tech-no-perm@test.com", password="pw", role=no_perm_role
        )
        patient = Patient.objects.create(
            full_name="Paciente Staff A",
            birth_date=date(1990, 1, 1),
            gender="F",
            cpf="54444444402",
        )
        self.own_study = DicomStudy.objects.create(
            patient=patient,
            study_instance_uid="1.2.3.staff.own",
            accession_number="staffown",
            modality="CT",
            study_date=datetime(2026, 7, 20, tzinfo=UTC),
            orthanc_study_id="stored-study",
            dicom_identity_verified=True,
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.staff)

    def _authorize(self, uri, client=None):
        client = client or self.client
        return client.get("/api/v1/portal/me/imaging-viewer-auth/", HTTP_X_ORIGINAL_URI=uri)

    def test_staff_authorized_for_study_in_own_tenant(self):
        """(b) module + RBAC + a UID that resolves in THIS tenant's schema →
        204, unchanged from before the fix."""
        response = self._authorize(
            f"/imagens-dicom/studies/{self.own_study.study_instance_uid}/series/1/instances/1"
        )
        self.assertEqual(response.status_code, 204)

    def test_staff_denied_for_uid_not_in_current_tenant_schema(self):
        """A UID absent from this tenant's DicomStudy table is denied. Because
        DicomStudy is a TENANT_APPS (per-schema) model, this is the exact
        query the view runs for a foreign-tenant UID too — from this
        connection there is no way to tell "doesn't exist" from "exists only
        in another clinic's schema" apart, which is the point. Failed before
        the fix (used to return 204 for any URI once module+RBAC passed)."""
        response = self._authorize(
            "/imagens-dicom/studies/1.2.3.nowhere-in-this-tenant/series/1/instances/1"
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_denied_for_study_in_another_tenant(self):
        """(a) End-to-end against a REAL second schema: a technician
        authenticated into Clinic B (a brand-new, empty tenant) must not be
        authorized for a study that only exists in Clinic A's schema (this
        class's own, already-populated fast_test tenant), even though
        imaging.read is a global RBAC grant shared across tenants (Role/User
        live in SHARED_APPS). This is the schema-isolation boundary from the
        report, traversed in the direction that's safe to set up/tear down
        inside a transactional test: tenant B is created and dropped EMPTY
        (no TENANT_APPS rows), because inserting DicomStudy/Patient rows into
        a schema created within this same atomic test transaction leaves
        deferred FK trigger events that block DROP SCHEMA at teardown — see
        apps/imaging/tests/test_orthanc_sync.py::OrthancSyncMultiTenantTest.
        Failed before the fix, for the same reason as the test above.
        """
        with schema_context(get_public_schema_name()):
            tenant_b = Tenant.objects.create(
                name="Clinic B (imaging auth test)", slug="clinicb-imgauth"
            )
            domain_b = Domain.objects.create(domain="clinicb-imgauth.test.com", tenant=tenant_b)
        FeatureFlag.objects.create(tenant=tenant_b, module_key="imaging", is_enabled=True)

        def _cleanup():
            domain_b.delete()
            with schema_context(get_public_schema_name()):
                try:
                    tenant_b.delete(force_drop=True)
                except Exception:
                    tenant_b.delete()

        self.addCleanup(_cleanup)

        client_b = APIClient()
        client_b.defaults["SERVER_NAME"] = domain_b.domain
        client_b.force_authenticate(self.staff)

        response = self._authorize(
            f"/imagens-dicom/studies/{self.own_study.study_instance_uid}/series/1/instances/1",
            client=client_b,
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_qido_without_uid_denied(self):
        """(c) generic QIDO listing (no UID at all) is a global-catalog
        vector — must be denied even with module + RBAC. Failed before the
        fix (204 for any URI)."""
        response = self._authorize("/imagens-dicom/studies")
        self.assertEqual(response.status_code, 403)

    def test_staff_qido_multi_uid_denied(self):
        """(d) multi-UID QIDO is a confused-deputy vector — denied even when
        one of the UIDs is legitimately owned. Failed before the fix."""
        response = self._authorize(
            "/imagens-dicom/studies?"
            f"StudyInstanceUID={self.own_study.study_instance_uid}&"
            "StudyInstanceUID=1.2.3.other"
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_without_imaging_read_denied(self):
        """(f) module without imaging.read still falls through to the
        (unmet) patient-portal branch → 403, unchanged from before the fix."""
        self.client.force_authenticate(self.staff_no_perm)
        response = self._authorize(
            f"/imagens-dicom/studies/{self.own_study.study_instance_uid}/series/1/instances/1"
        )
        self.assertEqual(response.status_code, 403)
