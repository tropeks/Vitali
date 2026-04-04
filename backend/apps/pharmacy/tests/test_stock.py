"""
S-027 Stock Management — test suite
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag
from apps.pharmacy.models import Drug, StockItem, StockMovement


def make_drug(**kwargs):
    defaults = {'name': 'Test Drug', 'unit_of_measure': 'un'}
    defaults.update(kwargs)
    return Drug.objects.create(**defaults)


def make_stock_item(drug=None, quantity=Decimal('0'), **kwargs):
    if drug is None:
        drug = make_drug()
    return StockItem.objects.create(drug=drug, quantity=quantity, lot_number='L001', **kwargs)


class TestStockMovementImmutability(TenantTestCase):
    def test_stockmovement_immutability(self):
        """Critical: update attempt must raise ValueError."""
        item = make_stock_item()
        mv = StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('10'))
        mv.save()
        mv.quantity = Decimal('99')
        with self.assertRaises(ValueError):
            mv.save()

    def test_stockmovement_delete_raises(self):
        item = make_stock_item()
        mv = StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('5'))
        mv.save()
        with self.assertRaises(ValueError):
            mv.delete()

    def test_stockitem_quantity_increments_via_f_expression(self):
        item = make_stock_item(quantity=Decimal('0'))
        StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('50')).save()
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal('50'))

    def test_stockitem_quantity_decrements_on_dispense(self):
        item = make_stock_item(quantity=Decimal('0'))
        StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('100')).save()
        StockMovement(stock_item=item, movement_type='dispense', quantity=Decimal('-30')).save()
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal('70'))


class TestStockNegativeGuard(TenantTestCase):
    def test_adjustment_negative_stock_raises(self):
        """A StockMovement that would drive quantity < 0 must raise ValueError."""
        item = make_stock_item(quantity=Decimal('0'))
        StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('5')).save()
        with self.assertRaises(ValueError) as ctx:
            StockMovement(stock_item=item, movement_type='adjustment', quantity=Decimal('-10')).save()
        self.assertIn('negativo', str(ctx.exception).lower())
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal('5'))  # unchanged

    def test_direct_dispense_movement_blocked_via_serializer(self):
        """POSTing movement_type='dispense' directly must be rejected by the serializer."""
        from rest_framework.exceptions import ValidationError
        from apps.pharmacy.serializers import StockMovementSerializer
        item = make_stock_item()
        s = StockMovementSerializer(data={
            'stock_item': str(item.id),
            'movement_type': 'dispense',
            'quantity': '-5',
        })
        s.is_valid()
        with self.assertRaises(ValidationError):
            s.validate({
                'stock_item': item,
                'movement_type': 'dispense',
                'quantity': Decimal('-5'),
            })


class TestStockEntryValidation(TenantTestCase):
    def test_expiry_date_past_raises_via_serializer(self):
        from rest_framework.exceptions import ValidationError
        from apps.pharmacy.serializers import StockMovementSerializer
        drug = make_drug()
        yesterday = (timezone.now() - timezone.timedelta(days=1)).date()
        item = StockItem.objects.create(
            drug=drug, lot_number='EXP001', expiry_date=yesterday
        )
        s = StockMovementSerializer(data={
            'stock_item': str(item.id),
            'movement_type': 'entry',
            'quantity': '10',
        })
        s.is_valid()
        with self.assertRaises(ValidationError):
            s.validate({'stock_item': item, 'movement_type': 'entry', 'quantity': Decimal('10')})


class TestCeleryTasks(TenantTestCase):
    @patch('apps.pharmacy.tasks._get_redis')
    @patch('apps.pharmacy.tasks.get_tenant_model')
    def test_celery_task_tenant_context(self, mock_get_tenant_model, mock_redis):
        """check_expiry_alerts must iterate tenants via schema_context."""
        from apps.pharmacy.tasks import check_expiry_alerts
        mock_tenant = MagicMock()
        mock_tenant.schema_name = 'tenant_test'
        mock_get_tenant_model.return_value.objects.exclude.return_value = [mock_tenant]
        mock_r = MagicMock()
        mock_redis.return_value = mock_r
        with patch('apps.pharmacy.tasks.schema_context') as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            check_expiry_alerts()
        mock_ctx.assert_called_once_with('tenant_test')

    @patch('apps.pharmacy.tasks._get_redis')
    def test_check_expiry_alerts_populates_redis_with_item_data(self, mock_redis):
        """Redis value must be item list, not just a count."""
        from apps.pharmacy.tasks import _check_expiry_alerts_for_tenant
        drug = make_drug(name='Expiring Drug')
        tomorrow = (timezone.now() + timezone.timedelta(days=1)).date()
        StockItem.objects.create(
            drug=drug, lot_number='EXP1', expiry_date=tomorrow, quantity=Decimal('5')
        )
        mock_r = MagicMock()
        mock_redis.return_value = mock_r
        _check_expiry_alerts_for_tenant('test_schema')
        mock_r.set.assert_called_once()
        import json
        key, value = mock_r.set.call_args[0][0], mock_r.set.call_args[0][1]
        self.assertEqual(key, 'pharmacy:test_schema:expiry_alerts')
        items = json.loads(value)
        self.assertEqual(len(items), 1)
        self.assertIn('name', items[0])
        self.assertIn('expiry_date', items[0])

    @patch('apps.pharmacy.tasks._get_redis')
    def test_check_min_stock_alerts_triggers_when_below_min(self, mock_redis):
        """Low stock alert fires when quantity < min_stock."""
        from apps.pharmacy.tasks import _check_min_stock_alerts_for_tenant
        drug = make_drug(name='Low Stock Drug')
        item = make_stock_item(drug=drug, min_stock=Decimal('10'))
        StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('3')).save()
        mock_r = MagicMock()
        mock_redis.return_value = mock_r
        _check_min_stock_alerts_for_tenant('test_schema')
        mock_r.set.assert_called_once()
        import json
        items = json.loads(mock_r.set.call_args[0][1])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'Low Stock Drug')


class TestStockAvailabilityEndpoint(TenantTestCase):
    def setUp(self):
        from apps.core.models import User, Role
        from apps.core.permissions import DEFAULT_ROLES
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='pharmacy', defaults={'is_enabled': True}
        )
        self.role = Role.objects.create(name='farmaceutico', permissions=DEFAULT_ROLES['farmaceutico'])
        self.user = User.objects.create_user(email='f@test.com', password='pw', role=self.role)

    def _client(self):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        c.force_authenticate(user=self.user)
        return c

    def test_stock_availability_requires_authenticated(self):
        c = APIClient()
        c.defaults['SERVER_NAME'] = self.__class__.domain.domain
        response = c.get('/api/v1/pharmacy/stock/availability/')
        self.assertEqual(response.status_code, 401)

    def test_stock_availability_authenticated_returns_lots(self):
        drug = make_drug()
        future = (timezone.now() + timezone.timedelta(days=90)).date()
        item = StockItem.objects.create(drug=drug, lot_number='AV1', expiry_date=future, quantity=Decimal('0'))
        StockMovement(stock_item=item, movement_type='entry', quantity=Decimal('20')).save()
        response = self._client().get(f'/api/v1/pharmacy/stock/availability/?drug={drug.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('available_lots', response.data)
