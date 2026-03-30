"""
Pharmacy API views — S-026 Catalog, S-027 Stock, S-028 Dispensation
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status, serializers as rf_serializers
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission

from .models import Drug, Material, StockItem, StockMovement, Dispensation, DispensationLot
from .serializers import (
    DrugSerializer,
    MaterialSerializer,
    StockItemSerializer,
    StockMovementSerializer,
    DispensationSerializer,
    DispenseRequestSerializer,
)


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=old_data,
        new_data=new_data,
        ip_address=request.META.get('REMOTE_ADDR', ''),
    )


# ─── S-026: Catalog ───────────────────────────────────────────────────────────

class DrugViewSet(viewsets.ModelViewSet):
    serializer_class = DrugSerializer

    def get_queryset(self):
        qs = Drug.objects.all()
        search = self.request.query_params.get('search')
        if search:
            # pg_trgm fuzzy search via LIKE (trigram index picks this up)
            qs = qs.filter(name__icontains=search) | qs.filter(generic_name__icontains=search)
        controlled = self.request.query_params.get('controlled')
        if controlled == 'true':
            qs = qs.exclude(controlled_class='none')
        active = self.request.query_params.get('active')
        if active == 'false':
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), HasPermission('pharmacy.catalog_manage')]
        return [IsAuthenticated(), HasPermission('pharmacy.read')]

    def perform_create(self, serializer):
        drug = serializer.save()
        log_audit(self.request, 'create', 'Drug', drug.id, new_data=serializer.data)

    def perform_update(self, serializer):
        old = DrugSerializer(serializer.instance).data
        drug = serializer.save()
        log_audit(self.request, 'update', 'Drug', drug.id, old_data=old, new_data=DrugSerializer(drug).data)

    def perform_destroy(self, instance):
        log_audit(self.request, 'delete', 'Drug', instance.id, old_data=DrugSerializer(instance).data)
        instance.is_active = False
        instance.save(update_fields=['is_active'])


class MaterialViewSet(viewsets.ModelViewSet):
    serializer_class = MaterialSerializer

    def get_queryset(self):
        qs = Material.objects.all()
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search)
        active = self.request.query_params.get('active')
        if active == 'false':
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), HasPermission('pharmacy.catalog_manage')]
        return [IsAuthenticated(), HasPermission('pharmacy.read')]

    def perform_create(self, serializer):
        material = serializer.save()
        log_audit(self.request, 'create', 'Material', material.id, new_data=serializer.data)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active'])


# ─── S-027: Stock ─────────────────────────────────────────────────────────────

class StockItemViewSet(viewsets.ModelViewSet):
    serializer_class = StockItemSerializer

    def get_queryset(self):
        qs = StockItem.objects.select_related('drug', 'material')
        drug_id = self.request.query_params.get('drug')
        if drug_id:
            qs = qs.filter(drug_id=drug_id)
        material_id = self.request.query_params.get('material')
        if material_id:
            qs = qs.filter(material_id=material_id)
        return qs

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'adjust'):
            return [IsAuthenticated(), HasPermission('pharmacy.stock_manage')]
        return [IsAuthenticated(), HasPermission('pharmacy.read')]

    @action(detail=True, methods=['post'], url_path='adjust')
    def adjust(self, request, pk=None):
        """POST /pharmacy/stock/items/{id}/adjust/ — create an adjustment StockMovement."""
        item = self.get_object()
        quantity = request.data.get('quantity')
        notes = request.data.get('notes', '')
        if quantity is None:
            return Response({'detail': 'quantity is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            qty = Decimal(str(quantity))
        except Exception:
            return Response({'detail': 'quantity must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            movement = StockMovement.objects.create(
                stock_item=item,
                movement_type='adjustment',
                quantity=qty,
                notes=notes,
                performed_by=request.user,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        log_audit(request, 'adjust', 'StockItem', item.id,
                  new_data={'quantity': str(qty), 'notes': notes})
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class StockMovementViewSet(viewsets.ModelViewSet):
    serializer_class = StockMovementSerializer
    http_method_names = ['get', 'post', 'head', 'options']  # no PUT/PATCH/DELETE (append-only)

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('pharmacy.stock_manage')]

    def get_queryset(self):
        qs = StockMovement.objects.select_related('stock_item', 'performed_by')
        stock_item_id = self.request.query_params.get('stock_item')
        if stock_item_id:
            qs = qs.filter(stock_item_id=stock_item_id)
        return qs

    def perform_create(self, serializer):
        movement = serializer.save(performed_by=self.request.user)
        log_audit(
            self.request, 'create', 'StockMovement', movement.id,
            new_data={'type': movement.movement_type, 'qty': str(movement.quantity)},
        )


class StockAlertsView(APIView):
    """GET /pharmacy/stock/alerts/ — returns cached expiry + low-stock alert lists from Redis."""
    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('pharmacy.read')]

    def get(self, request):
        import json
        from django.conf import settings
        schema = getattr(request.tenant, 'schema_name', 'public')
        cache_available = True
        try:
            import redis
            r = redis.from_url(getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0'))
            expiry_raw = r.get(f'pharmacy:{schema}:expiry_alerts')
            min_stock_raw = r.get(f'pharmacy:{schema}:min_stock_alerts')
            expiry_items = json.loads(expiry_raw) if expiry_raw else []
            min_stock_items = json.loads(min_stock_raw) if min_stock_raw else []
        except Exception:
            expiry_items = []
            min_stock_items = []
            cache_available = False
        return Response({
            'expiry_alerts': expiry_items,
            'min_stock_alerts': min_stock_items,
            'cache_available': cache_available,
        })


class StockAvailabilityView(APIView):
    """GET /pharmacy/stock/availability/?drug=<uuid> — returns available lots."""
    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('pharmacy.read')]

    def get(self, request):
        drug_id = request.query_params.get('drug')
        if not drug_id:
            return Response({'detail': 'drug query param required.'}, status=400)
        from django.db.models import Q
        today = timezone.now().date()
        lots = StockItem.objects.filter(
            drug_id=drug_id,
            quantity__gt=0,
        ).filter(
            Q(expiry_date__gte=today) | Q(expiry_date__isnull=True)
        ).order_by('expiry_date')
        data = StockItemSerializer(lots, many=True).data
        return Response({'available_lots': data, 'total': sum(float(l['quantity']) for l in data)})


# ─── S-028: Dispensation ──────────────────────────────────────────────────────

class DispensationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DispensationSerializer

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('pharmacy.dispense')]

    def get_queryset(self):
        qs = Dispensation.objects.select_related(
            'prescription', 'prescription_item', 'patient', 'dispensed_by'
        ).prefetch_related('lots__stock_item')
        patient_id = self.request.query_params.get('patient')
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        prescription_id = self.request.query_params.get('prescription')
        if prescription_id:
            qs = qs.filter(prescription_id=prescription_id)
        return qs


class DispenseView(APIView):
    """
    POST /pharmacy/dispense/
    Atomic FEFO dispensation across multiple lots.
    Requires signed Rx, checks controlled-substance role gate.
    """
    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('pharmacy.dispense')]

    def post(self, request):
        serializer = DispenseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from apps.emr.models import PrescriptionItem, Prescription
        try:
            rx_item = PrescriptionItem.objects.select_related(
                'prescription', 'drug', 'prescription__patient'
            ).get(pk=data['prescription_item_id'])
        except PrescriptionItem.DoesNotExist:
            return Response({'detail': 'PrescriptionItem not found.'}, status=404)

        prescription = rx_item.prescription
        drug = rx_item.drug

        # Gate 1: prescription must be signed and not cancelled/dispensed
        if prescription.status not in ('signed', 'partially_dispensed'):
            return Response(
                {'detail': 'Receita inválida. Só receitas assinadas podem ser dispensadas.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Gate 2: controlled substance requires dispense_controlled permission
        # Superuser bypass intentionally removed — ANVISA requires a named pharmacist record
        # for all controlled-substance dispensations regardless of account privilege.
        if drug.is_controlled:
            role = getattr(request.user, 'role', None)
            perms = role.permissions if role else []
            if 'pharmacy.dispense_controlled' not in perms:
                return Response(
                    {'detail': 'Permissão insuficiente para dispensar medicamento controlado.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Gate 3: controlled substances require notes
        if drug.is_controlled and not data.get('notes', '').strip():
            return Response(
                {'detail': 'Notas obrigatórias para dispensação de medicamento controlado.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        requested_qty = Decimal(str(data['quantity']))
        today = timezone.now().date()

        try:
            dispensation = self._dispense_fefo(
                request, prescription, rx_item, drug, requested_qty, data.get('notes', ''), today
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_audit(
            request, 'dispense', 'Dispensation', dispensation.id,
            new_data={
                'prescription_item': str(rx_item.id),
                'drug': drug.name,
                'quantity': str(requested_qty),
            },
        )
        return Response(DispensationSerializer(dispensation).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _dispense_fefo(self, request, prescription, rx_item, drug, requested_qty, notes, today):
        """
        FEFO: lock lots in expiry order, allocate greedily, raise ValueError if insufficient.
        The select_for_update + re-check inside the lock prevents negative stock.
        PrescriptionItem is also locked to prevent concurrent over-dispense.
        """
        from apps.emr.models import PrescriptionItem
        from django.db.models import Q as _Q, Sum

        # Lock the PrescriptionItem row first to prevent concurrent over-dispense.
        # Without this lock, two requests read already_dispensed=0 simultaneously
        # and both proceed to dispense the full quantity.
        rx_item = PrescriptionItem.objects.select_for_update().get(pk=rx_item.pk)

        lots = StockItem.objects.select_for_update(of=('self',)).filter(
            drug=drug,
        ).filter(
            _Q(expiry_date__gte=today) | _Q(expiry_date__isnull=True)
        ).order_by('expiry_date')

        # Guard: check already-dispensed quantity against prescribed quantity (inside lock)
        already_dispensed = (
            DispensationLot.objects.filter(
                dispensation__prescription_item=rx_item
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
        )
        remaining_prescribed = rx_item.quantity - already_dispensed
        if requested_qty > remaining_prescribed:
            raise ValueError(
                f'Quantidade solicitada ({requested_qty}) excede o saldo da receita '
                f'({remaining_prescribed}). Já dispensado: {already_dispensed}.'
            )

        # Re-check quantities after acquiring lock
        available = [(lot, lot.quantity) for lot in lots if lot.quantity > Decimal('0')]
        total_available = sum(q for _, q in available)

        if total_available < requested_qty:
            raise ValueError(
                f'Estoque insuficiente. Disponível: {total_available}, Solicitado: {requested_qty}'
            )

        dispensation = Dispensation.objects.create(
            prescription=prescription,
            prescription_item=rx_item,
            patient=prescription.patient,
            dispensed_by=request.user,
            notes=notes,
        )

        remaining = requested_qty
        for lot, available_qty in available:
            if remaining <= Decimal('0'):
                break
            take = min(available_qty, remaining)
            DispensationLot.objects.create(
                dispensation=dispensation,
                stock_item=lot,
                quantity=take,
            )
            # StockMovement.save() does the F()-based atomic decrement
            StockMovement.objects.create(
                stock_item=lot,
                movement_type='dispense',
                quantity=-take,
                reference=str(dispensation.id),
                notes=f'Dispensação {dispensation.id}',
                performed_by=request.user,
            )
            remaining -= take

        # Update Prescription.status inside the lock so reporting sees correct state.
        # Recompute total dispensed across ALL items on this Rx to determine new status.
        from apps.emr.models import Prescription as _Rx
        rx_locked = _Rx.objects.select_for_update().get(pk=prescription.pk)
        all_items = rx_locked.items.all()
        all_fully_dispensed = all(
            (DispensationLot.objects.filter(
                dispensation__prescription_item=item
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')) >= item.quantity
            for item in all_items
        )
        if all_fully_dispensed:
            rx_locked.status = 'dispensed'
        else:
            rx_locked.status = 'partially_dispensed'
        rx_locked.save(update_fields=['status'])

        return dispensation
