from datetime import UTC, date, datetime

from apps.core.models import Role, User
from apps.emr.models import Patient
from apps.imaging.models import DicomWorkflowEvent, ImagingModality, ModalityWorklistItem
from apps.imaging.services.workflow import apply_workflow_event, record_echo
from apps.test_utils import TenantTestCase


class EnterpriseImagingWorkflowTest(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="ris", permissions=["imaging.read", "imaging.write"])
        self.user = User.objects.create_user(email="ris@test.local", password="pw", role=role)
        self.patient = Patient.objects.create(
            full_name="Paciente RIS", birth_date=date(1980, 1, 1), gender="M"
        )
        self.modality = ImagingModality.objects.create(
            ae_title="VITALI_MR", name="RM 1", modality="MR", host="10.0.0.10"
        )
        self.worklist = ModalityWorklistItem.objects.create(
            modality=self.modality,
            patient=self.patient,
            accession_number="ACC-RIS-1",
            requested_procedure_id="MR-BRAIN",
            requested_procedure_description="RM crânio",
            scheduled_at=datetime(2026, 7, 22, tzinfo=UTC),
            created_by=self.user,
        )

    def test_echo_and_idempotent_mpps_completion(self):
        record_echo(self.modality, True, self.user)
        event, created = apply_workflow_event(
            self.worklist,
            self.modality,
            "1.2.3.4",
            DicomWorkflowEvent.Type.MPPS_COMPLETED,
            {"study_instance_uid": "1.2.840.1"},
            self.user,
        )
        duplicate, duplicate_created = apply_workflow_event(
            self.worklist,
            self.modality,
            "1.2.3.4",
            DicomWorkflowEvent.Type.MPPS_COMPLETED,
            {},
            self.user,
        )
        self.worklist.refresh_from_db()
        self.modality.refresh_from_db()
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(event.id, duplicate.id)
        self.assertEqual(self.worklist.status, ModalityWorklistItem.Status.COMPLETED)
        self.assertTrue(self.modality.last_echo_ok)
