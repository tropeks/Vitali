from decimal import Decimal

from rest_framework import serializers
from .models import Drug, Material, StockItem, StockMovement, Dispensation, DispensationLot


class DrugSerializer(serializers.ModelSerializer):
    controlled_class_display = serializers.CharField(
        source='get_controlled_class_display', read_only=True
    )
    is_controlled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Drug
        fields = [
            'id', 'name', 'generic_name', 'anvisa_code', 'barcode',
            'dosage_form', 'concentration', 'unit_of_measure',
            'controlled_class', 'controlled_class_display', 'is_controlled',
            'is_active', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = [
            'id', 'name', 'category', 'barcode', 'unit_of_measure',
            'is_active', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class StockItemSerializer(serializers.ModelSerializer):
    drug_name = serializers.CharField(source='drug.name', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()

    class Meta:
        model = StockItem
        fields = [
            'id', 'drug', 'drug_name', 'material', 'material_name',
            'lot_number', 'expiry_date', 'quantity', 'min_stock',
            'location', 'is_expired', 'is_low_stock', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'quantity', 'created_at', 'updated_at']

    def get_is_expired(self, obj):
        from django.utils import timezone
        if obj.expiry_date:
            return obj.expiry_date < timezone.now().date()
        return False

    def get_is_low_stock(self, obj):
        return obj.quantity <= obj.min_stock


class StockMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(
        source='get_movement_type_display', read_only=True
    )
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            'id', 'stock_item', 'movement_type', 'movement_type_display',
            'quantity', 'reference', 'notes', 'performed_by', 'performed_by_name',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return obj.performed_by.full_name or obj.performed_by.email
        return None

    def validate(self, attrs):
        movement_type = attrs.get('movement_type')
        stock_item = attrs.get('stock_item')
        from django.utils import timezone
        # Dispense movements must only be created through DispenseView (FEFO + Rx gate)
        if movement_type == 'dispense':
            raise serializers.ValidationError(
                {'movement_type': 'Dispensações devem ser registradas via /pharmacy/dispense/.'}
            )
        # Validate expiry_date for entries
        if movement_type == 'entry' and stock_item and stock_item.expiry_date:
            if stock_item.expiry_date < timezone.now().date():
                raise serializers.ValidationError(
                    {'expiry_date': 'Lote já vencido não pode ser adicionado ao estoque.'}
                )
        return attrs


class DispensationLotSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispensationLot
        fields = ['id', 'stock_item', 'quantity']
        read_only_fields = ['id']


class DispensationSerializer(serializers.ModelSerializer):
    lots = DispensationLotSerializer(many=True, read_only=True)
    total_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    dispensed_by_name = serializers.SerializerMethodField()
    drug_name = serializers.SerializerMethodField()

    class Meta:
        model = Dispensation
        fields = [
            'id', 'prescription', 'prescription_item', 'patient',
            'dispensed_by', 'dispensed_by_name', 'drug_name',
            'notes', 'dispensed_at', 'lots', 'total_quantity',
        ]
        read_only_fields = ['id', 'dispensed_at', 'dispensed_by']

    def get_dispensed_by_name(self, obj):
        return obj.dispensed_by.full_name or obj.dispensed_by.email

    def get_drug_name(self, obj):
        try:
            return obj.prescription_item.drug.name
        except AttributeError:
            return None


class DispenseRequestSerializer(serializers.Serializer):
    """Input for POST /pharmacy/dispense/ — the action serializer."""
    prescription_item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0.001'))
    notes = serializers.CharField(required=False, allow_blank=True, default='')
