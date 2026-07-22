from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    Encounter,
    NursingAssessment,
    Patient,
    Prescription,
    PrescriptionItem,
    Professional,
)
from apps.emr.serializers import NursingAssessmentSerializer
from apps.emr.services.clinical_operations import MedicationAdministrationService
from apps.pharmacy.models import Drug, PharmacistValidation
from apps.test_utils import TenantTestCase


class ClinicalOperationsTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.role = Role.objects.create(
            name="clinical_operations_test",
            permissions=["emr.write", "emar.read", "emar.administer", "sae.read", "sae.write"],
        )
        self.user = User.objects.create_user(
            email="nurse-ops@test.local", password="pw", role=self.role
        )
        self.patient = Patient.objects.create(
            full_name="Paciente", cpf="12345678901", birth_date="1980-01-01", gender="F"
        )
        self.professional = Professional.objects.create(
            user=self.user, council_type="COREN", council_number="1", council_state="SP"
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.drug = Drug.objects.create(name="Dipirona", generic_name="dipirona")
        self.prescription = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.professional
        )
        self.item = PrescriptionItem.objects.create(
            prescription=self.prescription, drug=self.drug, quantity=Decimal("1")
        )
        self.slot = timezone.now() + timedelta(hours=1)

    def test_emar_requires_signed_and_pharmacist_approved_order(self):
        with self.assertRaisesMessage(ValidationError, "ordem deve estar assinada"):
            MedicationAdministrationService.record(
                prescription_item=self.item, scheduled_at=self.slot, status="given", user=self.user
            )
        self.prescription.sign(self.user)
        with self.assertRaisesMessage(ValidationError, "farmacêutica aprovada"):
            MedicationAdministrationService.record(
                prescription_item=self.item, scheduled_at=self.slot, status="given", user=self.user
            )
        PharmacistValidation.objects.create(
            prescription=self.prescription,
            status="approved",
            pharmacist=self.user,
            validated_at=timezone.now(),
        )
        event = MedicationAdministrationService.record(
            prescription_item=self.item, scheduled_at=self.slot, status="given", user=self.user
        )
        self.assertEqual(event.patient, self.patient)
        self.assertEqual(event.encounter, self.encounter)

    def test_emar_non_administration_requires_reason(self):
        self.prescription.sign(self.user)
        PharmacistValidation.objects.create(prescription=self.prescription, status="approved")
        with self.assertRaisesMessage(ValidationError, "motivo"):
            MedicationAdministrationService.record(
                prescription_item=self.item, scheduled_at=self.slot, status="held", user=self.user
            )

    def test_signed_sae_is_immutable(self):
        assessment = NursingAssessment.objects.create(
            encounter=self.encounter,
            patient=self.patient,
            kind="evolution",
            content={"note": "estável"},
            authored_by=self.user,
            signed_at=timezone.now(),
            signed_by=self.user,
        )
        serializer = NursingAssessmentSerializer(
            assessment, data={"content": {"note": "alterada"}}, partial=True
        )
        self.assertFalse(serializer.is_valid())

    def test_emar_rbac_denies_user_without_permission(self):
        other_role = Role.objects.create(name="no_emar", permissions=["emr.read"])
        other = User.objects.create_user(email="no-emar@test.local", password="pw", role=other_role)
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(other)
        response = client.get("/api/v1/emar/")
        self.assertEqual(response.status_code, 403)
