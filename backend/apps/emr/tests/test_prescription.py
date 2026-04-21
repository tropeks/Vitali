"""
S-015 Prescription — sign action, status transition, generic_name auto-population.
"""
from decimal import Decimal

from apps.test_utils import TenantTestCase
from rest_framework.test import APIClient

from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Prescription, PrescriptionItem, Patient, Professional, Encounter
from apps.pharmacy.models import Drug


def _make_infra():
    from apps.core.models import User, Role
    role_md = Role.objects.create(name='medico_px', permissions=DEFAULT_ROLES['medico'])
    role_enf = Role.objects.create(name='enfermeiro_px', permissions=DEFAULT_ROLES['enfermeiro'])
    medico_user = User.objects.create_user(email='md_px@t.com', password='pw', role=role_md)
    enf_user = User.objects.create_user(email='enf_px@t.com', password='pw', role=role_enf)
    patient = Patient.objects.create(
        full_name='Prescription Patient', birth_date='1985-06-15', gender='F', cpf='22222222222'
    )
    prescriber = Professional.objects.create(
        user=medico_user, council_type='CRM', council_number='5', council_state='RJ'
    )
    encounter = Encounter.objects.create(patient=patient, professional=prescriber)
    return medico_user, enf_user, patient, prescriber, encounter


class TestPrescriptionModel(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prescriber, self.encounter = _make_infra()

    def test_prescription_status_transition_draft_to_signed(self):
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        self.assertEqual(rx.status, 'draft')
        self.assertFalse(rx.is_signed)
        rx.sign(self.medico_user)
        self.assertEqual(rx.status, 'signed')
        self.assertTrue(rx.is_signed)
        self.assertIsNotNone(rx.signed_at)

    def test_prescription_item_generic_name_auto_populated(self):
        drug = Drug.objects.create(
            name='Amoxicilina 500mg', generic_name='amoxicilina tri-hidratada'
        )
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        item = PrescriptionItem.objects.create(
            prescription=rx, drug=drug, quantity=Decimal('21')
        )
        self.assertEqual(item.generic_name, 'amoxicilina tri-hidratada')


class TestPrescriptionSignAPI(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prescriber, self.encounter = _make_infra()

    def _client(self, user):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def test_prescription_sign_action_requires_emr_sign_role(self):
        """Enfermeiro (no emr.sign) must get 403 on sign."""
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        resp = self._client(self.enf_user).post(f'/api/v1/prescriptions/{rx.id}/sign/')
        self.assertEqual(resp.status_code, 403)

    def test_prescription_sign_action_succeeds_for_medico(self):
        """Médico (has emr.sign) can sign the prescription."""
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        resp = self._client(self.medico_user).post(f'/api/v1/prescriptions/{rx.id}/sign/')
        self.assertEqual(resp.status_code, 200)
        rx.refresh_from_db()
        self.assertEqual(rx.status, 'signed')

    def test_add_item_to_signed_prescription_rejected(self):
        """Adding a PrescriptionItem to a signed Rx must return 400."""
        drug = Drug.objects.create(name='Drug For Signed Rx Test')
        rx = Prescription.objects.create(
            encounter=self.encounter, patient=self.patient, prescriber=self.prescriber
        )
        rx.sign(self.medico_user)
        resp = self._client(self.medico_user).post('/api/v1/prescription-items/', {
            'prescription': str(rx.id),
            'drug': str(drug.id),
            'quantity': '2',
            'unit_of_measure': 'un',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        import json
        body = json.dumps(resp.data).lower()
        self.assertIn('assinada', body)
