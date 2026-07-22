from apps.core.models import Role, User
from apps.emr.models import Encounter, Patient, Prescription, Professional
from apps.pharmacy.models import PharmacistValidation
from apps.pharmacy.serializers import PharmacistValidationSerializer
from apps.test_utils import TenantTestCase


class PharmacistValidationTests(TenantTestCase):
    def setUp(self):
        role = Role.objects.create(
            name="pharmacist_validation_test", permissions=["pharmacy.clinical_validate"]
        )
        self.user = User.objects.create_user(
            email="pharmacist@test.local", password="pw", role=role
        )
        patient = Patient.objects.create(
            full_name="Paciente", cpf="98765432100", birth_date="1970-01-01", gender="M"
        )
        professional = Professional.objects.create(
            user=self.user, council_type="CRF", council_number="2", council_state="SP"
        )
        encounter = Encounter.objects.create(patient=patient, professional=professional)
        self.prescription = Prescription.objects.create(
            encounter=encounter, patient=patient, prescriber=professional
        )

    def test_only_signed_prescription_enters_validation_queue(self):
        serializer = PharmacistValidationSerializer(
            data={"prescription": str(self.prescription.id)}
        )
        self.assertFalse(serializer.is_valid())
        self.prescription.sign(self.user)
        serializer = PharmacistValidationSerializer(
            data={"prescription": str(self.prescription.id)}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        validation = serializer.save()
        self.assertEqual(validation.status, PharmacistValidation.Status.PENDING)
