"""
S-028 Dispensation — FEFO, lot atomicity, role gates, Rx validation.
"""
from decimal import Decimal

from django.utils import timezone
from apps.test_utils import TenantTestCase
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import Drug, StockItem, StockMovement, Dispensation, DispensationLot


def _make_user(email, role_name):
    from apps.core.models import User, Role
    role = Role.objects.create(name=role_name + '_d', permissions=DEFAULT_ROLES[role_name])
    return User.objects.create_user(email=email, password='pw', role=role)


def _make_drug(controlled_class='none', **kwargs):
    kwargs.setdefault('name', 'TestDrug')
    return Drug.objects.create(controlled_class=controlled_class, **kwargs)


def _make_lot(drug, quantity, days_until_expiry=90, lot_number=None):
    future = (timezone.now() + timezone.timedelta(days=days_until_expiry)).date()
    item = StockItem.objects.create(
        drug=drug, lot_number=lot_number or f'LOT{days_until_expiry}', expiry_date=future
    )
    StockMovement(stock_item=item, movement_type='entry', quantity=quantity).save()
    return item


def _make_prescription(patient, prescriber, encounter, drug, qty=Decimal('5'), signed=True):
    from apps.emr.models import Prescription, PrescriptionItem
    rx = Prescription.objects.create(
        encounter=encounter, patient=patient, prescriber=prescriber
    )
    if signed:
        rx.sign(prescriber.user)
    item = PrescriptionItem.objects.create(
        prescription=rx, drug=drug, quantity=qty, unit_of_measure='un'
    )
    return rx, item


class TestFEFOUnit(TenantTestCase):
    def test_fefo_selects_earliest_non_expired_lot_first(self):
        """FEFO: the lot expiring soonest must be selected first."""
        drug = _make_drug()
        _make_lot(drug, Decimal('10'), days_until_expiry=180, lot_number='FAR')
        _make_lot(drug, Decimal('10'), days_until_expiry=30, lot_number='NEAR')
        today = timezone.now().date()
        lots = StockItem.objects.filter(
            drug=drug, quantity__gt=0, expiry_date__gte=today
        ).order_by('expiry_date')
        self.assertEqual(lots.first().lot_number, 'NEAR')

    def test_dispensation_total_quantity_equals_sum_of_lots(self):
        """total_quantity property must equal SUM(DispensationLot.quantity)."""
        from apps.emr.models import Patient, Professional, Encounter, Prescription, PrescriptionItem
        from apps.core.models import User, Role
        drug = _make_drug()
        lot1 = _make_lot(drug, Decimal('5'), days_until_expiry=30)
        lot2 = _make_lot(drug, Decimal('7'), days_until_expiry=60)
        role = Role.objects.create(name='medico_t', permissions=DEFAULT_ROLES['medico'])
        user = User.objects.create_user(email='md@t.com', password='pw', role=role)
        patient = Patient.objects.create(full_name='P', birth_date='1990-01-01', gender='M', cpf='00000000000')
        prof = Professional.objects.create(user=user, council_type='CRM', council_number='99', council_state='SP')
        encounter = Encounter.objects.create(patient=patient, professional=prof)
        rx = Prescription.objects.create(encounter=encounter, patient=patient, prescriber=prof)
        rx.sign(user)
        rx_item = PrescriptionItem.objects.create(prescription=rx, drug=drug, quantity=Decimal('12'))
        disp = Dispensation.objects.create(
            prescription=rx, prescription_item=rx_item, patient=patient, dispensed_by=user
        )
        DispensationLot.objects.create(dispensation=disp, stock_item=lot1, quantity=Decimal('5'))
        DispensationLot.objects.create(dispensation=disp, stock_item=lot2, quantity=Decimal('7'))
        self.assertEqual(disp.total_quantity, Decimal('12'))


class TestFEFOIntegration(TenantTestCase):
    def setUp(self):
        from apps.core.models import User, Role
        from apps.emr.models import Patient, Professional, Encounter
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='pharmacy', defaults={'is_enabled': True}
        )
        self.farmaceutico = _make_user('farm@t.com', 'farmaceutico')
        self.enfermeiro = _make_user('enf@t.com', 'enfermeiro')
        role_md = Role.objects.create(name='medico_i', permissions=DEFAULT_ROLES['medico'])
        self.medico_user = User.objects.create_user(email='md@t.com', password='pw', role=role_md)
        self.patient = Patient.objects.create(
            full_name='Patient', birth_date='1990-01-01', gender='M', cpf='11111111111'
        )
        self.prescriber = Professional.objects.create(
            user=self.medico_user, council_type='CRM', council_number='1', council_state='SP'
        )
        self.encounter = Encounter.objects.create(patient=self.patient, professional=self.prescriber)

    def _client(self, user):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def test_fefo_spans_multiple_lots(self):
        """Dispensing more than one lot's quantity must create N DispensationLot rows."""
        drug = _make_drug()
        _make_lot(drug, Decimal('3'), days_until_expiry=10, lot_number='SOON')
        _make_lot(drug, Decimal('10'), days_until_expiry=90, lot_number='LATER')
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('10'))
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '10',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        disp = Dispensation.objects.get(pk=resp.data['id'])
        self.assertEqual(disp.lots.count(), 2)

    def test_fefo_no_negative_stock_under_lock(self):
        """Dispensing > available must return 400, not create negative stock."""
        drug = _make_drug()
        _make_lot(drug, Decimal('5'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('99'))
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '99',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('insuficiente', resp.data['detail'].lower())

    def test_unsigned_prescription_rejected(self):
        """Dispensing against unsigned Rx must return 400."""
        drug = _make_drug()
        _make_lot(drug, Decimal('10'), days_until_expiry=60)
        rx, rx_item = _make_prescription(
            self.patient, self.prescriber, self.encounter, drug, signed=False
        )
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '5',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_controlled_substance_role_gate(self):
        """Enfermeiro must get 403 when dispensing controlled drug."""
        drug = _make_drug(controlled_class='B1', name='Diazepam')
        _make_lot(drug, Decimal('10'), days_until_expiry=60)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug)
        resp = self._client(self.enfermeiro).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '2',
            'notes': 'Some notes',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_controlled_without_notes_returns_400(self):
        """Controlled drug dispense without notes field must return 400."""
        drug = _make_drug(controlled_class='B1', name='Midazolam')
        _make_lot(drug, Decimal('10'), days_until_expiry=60)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug)
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '2',
            'notes': '',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_dispense_fills_lot_exactly(self):
        """Dispensing exactly the lot's quantity must leave StockItem.quantity = 0."""
        drug = _make_drug()
        lot = _make_lot(drug, Decimal('10'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('10'))
        self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '10',
        }, format='json')
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal('0'))

    def test_dispensation_lot_atomicity(self):
        """If FEFO logic fails mid-way, no partial Dispensation or StockMovement is created."""
        drug = _make_drug()
        _make_lot(drug, Decimal('5'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('20'))
        disp_count_before = Dispensation.objects.count()
        mv_count_before = StockMovement.objects.count()
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '20',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Dispensation.objects.count(), disp_count_before)
        self.assertEqual(StockMovement.objects.count(), mv_count_before)

    def test_partial_dispensation_respects_remaining_qty(self):
        """Second dispense on same Rx item sees already-depleted stock."""
        drug = _make_drug()
        lot = _make_lot(drug, Decimal('10'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('10'))
        client = self._client(self.farmaceutico)
        client.post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '6',
        }, format='json')
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal('4'))
        resp = client.post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '6',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_over_dispense_beyond_prescribed_quantity_rejected(self):
        """Dispensing > prescribed quantity on an Rx item must return 400."""
        drug = _make_drug()
        _make_lot(drug, Decimal('20'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('5'))
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '10',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('excede', resp.data['detail'].lower())

    def test_double_dispense_rejected_after_full_fill(self):
        """After fully dispensing an Rx item, a second dispense must return 400."""
        drug = _make_drug()
        _make_lot(drug, Decimal('20'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('5'))
        client = self._client(self.farmaceutico)
        first = client.post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '5',
        }, format='json')
        self.assertEqual(first.status_code, 201)
        second = client.post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '1',
        }, format='json')
        self.assertEqual(second.status_code, 400)

    def test_cancelled_prescription_rejected(self):
        """Dispensing against a cancelled (previously-signed) Rx must return 400."""
        drug = _make_drug()
        _make_lot(drug, Decimal('10'), days_until_expiry=60)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug)
        rx.status = 'cancelled'
        rx.save(update_fields=['status'])
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '5',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_fefo_null_expiry_lot_included(self):
        """A lot with no expiry date must be eligible for FEFO dispensation."""
        drug = _make_drug()
        # Create a lot with expiry_date=None
        item = StockItem.objects.create(drug=drug, lot_number='NO_EXPIRY', expiry_date=None)
        StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('10')).save()
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('5'))
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '5',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal('5'))

    def test_zero_quantity_dispense_rejected(self):
        """Dispensing quantity=0 must return 400 (min_value=0.001 guard)."""
        drug = _make_drug()
        _make_lot(drug, Decimal('10'), days_until_expiry=60)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug)
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '0',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_stock_availability_requires_pharmacy_read_permission(self):
        """Recepcionista (no pharmacy.read) must get 403 from stock availability endpoint."""
        from apps.core.models import User, Role
        role_recep = Role.objects.create(name='recep_av', permissions=DEFAULT_ROLES['recepcionista'])
        recep_user = User.objects.create_user(email='recep_av@t.com', password='pw', role=role_recep)
        from rest_framework.test import APIClient
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        c.force_authenticate(user=recep_user)
        drug = _make_drug()
        resp = c.get(f'/api/v1/pharmacy/stock/availability/?drug={drug.id}')
        self.assertEqual(resp.status_code, 403)

    def test_stock_availability_missing_drug_param_returns_400(self):
        """GET /pharmacy/stock/availability/ without ?drug= must return 400."""
        resp = self._client(self.farmaceutico).get('/api/v1/pharmacy/stock/availability/')
        self.assertEqual(resp.status_code, 400)

    def test_dispense_prescription_item_not_found_returns_404(self):
        """Dispensing against a non-existent PrescriptionItem UUID must return 404."""
        import uuid
        resp = self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(uuid.uuid4()),
            'quantity': '1',
        }, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_prescription_status_updated_after_partial_dispense(self):
        """Prescription.status must become 'partially_dispensed' after a partial fill."""
        drug = _make_drug()
        _make_lot(drug, Decimal('20'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('10'))
        self.assertEqual(rx.status, 'signed')
        self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '6',
        }, format='json')
        rx.refresh_from_db()
        self.assertEqual(rx.status, 'partially_dispensed')

    def test_prescription_status_updated_after_full_dispense(self):
        """Prescription.status must become 'dispensed' after all items are fully filled."""
        drug = _make_drug()
        _make_lot(drug, Decimal('20'), days_until_expiry=30)
        rx, rx_item = _make_prescription(self.patient, self.prescriber, self.encounter, drug, qty=Decimal('10'))
        self._client(self.farmaceutico).post('/api/v1/pharmacy/dispense/', {
            'prescription_item_id': str(rx_item.id),
            'quantity': '10',
        }, format='json')
        rx.refresh_from_db()
        self.assertEqual(rx.status, 'dispensed')
