"""
S-026 Drug & Material Catalog — test suite
"""
from django.db import IntegrityError
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.core.permissions import DEFAULT_ROLES
from apps.pharmacy.models import Drug, Material


class TestDrugModel(TenantTestCase):
    def test_drug_create_controlled_with_anvisa(self):
        drug = Drug.objects.create(
            name='Morfina 10mg/mL',
            generic_name='Morfina',
            anvisa_code='1234567890123',
            dosage_form='Solução injetável',
            concentration='10mg/mL',
            controlled_class='A1',
        )
        self.assertEqual(drug.controlled_class, 'A1')
        self.assertTrue(drug.is_controlled)
        self.assertEqual(drug.anvisa_code, '1234567890123')

    def test_drug_create_duplicate_barcode_raises(self):
        Drug.objects.create(name='Drug A', barcode='7891234567890')
        with self.assertRaises(IntegrityError):
            Drug.objects.create(name='Drug B', barcode='7891234567890')

    def test_drug_not_controlled_by_default(self):
        drug = Drug.objects.create(name='Paracetamol 500mg')
        self.assertFalse(drug.is_controlled)
        self.assertEqual(drug.controlled_class, 'none')

    def test_material_create_and_update(self):
        mat = Material.objects.create(name='Luva nitrílica G', category='EPI', unit_of_measure='par')
        self.assertEqual(mat.name, 'Luva nitrílica G')
        mat.category = 'Descartável'
        mat.save()
        mat.refresh_from_db()
        self.assertEqual(mat.category, 'Descartável')


class TestCatalogPermissions(TenantTestCase):
    def test_pharmacy_catalog_manage_in_farmaceutico_default_roles(self):
        self.assertIn('pharmacy.catalog_manage', DEFAULT_ROLES['farmaceutico'])

    def test_pharmacy_stock_manage_in_admin_default_roles(self):
        self.assertIn('pharmacy.stock_manage', DEFAULT_ROLES['admin'])

    def test_pharmacy_dispense_controlled_not_in_enfermeiro(self):
        self.assertNotIn('pharmacy.dispense_controlled', DEFAULT_ROLES['enfermeiro'])

    def test_pharmacy_dispense_controlled_in_farmaceutico(self):
        self.assertIn('pharmacy.dispense_controlled', DEFAULT_ROLES['farmaceutico'])


class TestCatalogAPI(TenantTestCase):
    def setUp(self):
        from apps.core.models import User, Role
        self.role_farmaceutico = Role.objects.create(
            name='farmaceutico',
            permissions=DEFAULT_ROLES['farmaceutico'],
        )
        self.role_recepcionista = Role.objects.create(
            name='recepcionista',
            permissions=DEFAULT_ROLES['recepcionista'],
        )
        self.farmaceutico = User.objects.create_user(
            email='farm@test.com', password='pw', role=self.role_farmaceutico
        )
        self.recepcionista = User.objects.create_user(
            email='recep@test.com', password='pw', role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def test_drug_list_farmaceutico_200(self):
        response = self._client(self.farmaceutico).get('/api/v1/pharmacy/drugs/')
        self.assertEqual(response.status_code, 200)

    def test_drug_list_recepcionista_403(self):
        response = self._client(self.recepcionista).get('/api/v1/pharmacy/drugs/')
        self.assertEqual(response.status_code, 403)

    def test_drug_fuzzy_search(self):
        Drug.objects.create(name='Amoxicilina 500mg', generic_name='amoxicilina', is_active=True)
        Drug.objects.create(name='Paracetamol 500mg', is_active=True)
        response = self._client(self.farmaceutico).get('/api/v1/pharmacy/drugs/?search=amox')
        self.assertEqual(response.status_code, 200)
        names = [d['name'] for d in response.data.get('results', response.data)]
        self.assertTrue(any('Amoxicilina' in n for n in names))
        self.assertFalse(any('Paracetamol' in n for n in names))

    def test_material_barcode_search(self):
        Material.objects.create(name='Seringa 10mL', barcode='1111111111111', is_active=True)
        response = self._client(self.farmaceutico).get('/api/v1/pharmacy/materials/?search=Seringa')
        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data)
        self.assertTrue(len(results) >= 1)
