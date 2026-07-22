from datetime import date

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import Role, User
from apps.emr.models import LabOrder, LabOrderItem, LabSpecimen, LabTest, Patient
from apps.emr.services.diagnostics import (
    acknowledge_critical_result,
    open_critical_result,
    transition_specimen,
)
from apps.test_utils import TenantTestCase


class EnterpriseDiagnosticsTest(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(name="diagnostics", permissions=["emr.read", "emr.write"])
        self.user = User.objects.create_user(email="diag@test.local", password="pw", role=role)
        patient = Patient.objects.create(
            full_name="Paciente Diagnóstico", birth_date=date(1990, 1, 1), gender="F"
        )
        self.order = LabOrder.objects.create(patient=patient, requested_by=self.user)
        test = LabTest.objects.create(code="K", name="Potássio")
        self.item = LabOrderItem.objects.create(order=self.order, test=test, test_name=test.name)

    def test_specimen_chain_of_custody_enforces_transitions(self):
        specimen = LabSpecimen.objects.create(
            order=self.order, barcode="BC-001", specimen_type="blood"
        )
        specimen = transition_specimen(
            specimen, LabSpecimen.Status.COLLECTED, self.user, location="collection"
        )
        specimen = transition_specimen(
            specimen, LabSpecimen.Status.RECEIVED, self.user, location="lab"
        )
        self.assertEqual(specimen.events.count(), 2)
        self.assertEqual(specimen.current_location, "lab")
        with self.assertRaises(ValidationError):
            transition_specimen(specimen, LabSpecimen.Status.DISPOSED, self.user)

    def test_critical_result_requires_closed_loop_acknowledgement(self):
        self.item.abnormal_flag = LabOrderItem.AbnormalFlag.CRITICAL
        self.item.resulted_at = timezone.now()
        self.item.save(update_fields=["abnormal_flag", "resulted_at"])
        critical = open_critical_result(self.item, self.user)
        critical = acknowledge_critical_result(
            critical, self.user, "Comunicado ao médico responsável"
        )
        self.assertEqual(critical.status, critical.Status.ACKNOWLEDGED)
        self.assertIsNotNone(critical.acknowledged_at)
