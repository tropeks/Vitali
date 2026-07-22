from decimal import Decimal

from rest_framework import serializers

from .models import (
    AllergenClass,
    Dispensation,
    DispensationLot,
    DoseRule,
    Drug,
    DrugInteraction,
    InventoryCount,
    InventoryCountLine,
    LotRecall,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    StockItem,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    StorageLocation,
    Supplier,
    Warehouse,
)


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = "__all__"


class StorageLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorageLocation
        fields = "__all__"


class InventoryCountLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryCountLine
        fields = ("id", "stock_item", "counted_quantity", "system_quantity_snapshot")
        read_only_fields = ("system_quantity_snapshot",)


class InventoryCountSerializer(serializers.ModelSerializer):
    lines = InventoryCountLineSerializer(many=True)

    class Meta:
        model = InventoryCount
        fields = (
            "id",
            "warehouse",
            "status",
            "blind",
            "approval",
            "created_at",
            "applied_at",
            "lines",
        )
        read_only_fields = ("status", "blind", "approval", "created_at", "applied_at")

    def create(self, validated_data):
        lines = validated_data.pop("lines")
        row = InventoryCount.objects.create(
            requested_by=self.context["request"].user, **validated_data
        )
        InventoryCountLine.objects.bulk_create(
            [InventoryCountLine(inventory=row, **line) for line in lines]
        )
        return row


class StockTransferLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransferLine
        fields = ("id", "source_item", "destination_item", "quantity")
        read_only_fields = ("destination_item",)


class StockTransferSerializer(serializers.ModelSerializer):
    lines = StockTransferLineSerializer(many=True)

    class Meta:
        model = StockTransfer
        fields = ("id", "origin", "destination", "status", "shipped_at", "accepted_at", "lines")
        read_only_fields = ("status", "shipped_at", "accepted_at")

    def create(self, validated_data):
        lines = validated_data.pop("lines")
        row = StockTransfer.objects.create(
            requested_by=self.context["request"].user, **validated_data
        )
        StockTransferLine.objects.bulk_create(
            [StockTransferLine(transfer=row, **line) for line in lines]
        )
        return row

    def validate(self, attrs):
        if attrs.get("origin") == attrs.get("destination"):
            raise serializers.ValidationError("Origem e destino devem ser diferentes.")
        return attrs


class LotRecallSerializer(serializers.ModelSerializer):
    affected_patients = serializers.SerializerMethodField()
    affected_destinations = serializers.SerializerMethodField()

    class Meta:
        model = LotRecall
        fields = (
            "id",
            "lot_number",
            "drug",
            "material",
            "reason",
            "status",
            "created_at",
            "affected_patients",
            "affected_destinations",
        )
        read_only_fields = ("status", "created_at", "affected_patients", "affected_destinations")

    def _lots(self, obj):
        return StockItem.objects.filter(
            lot_number=obj.lot_number, drug=obj.drug, material=obj.material
        )

    def validate(self, attrs):
        if bool(attrs.get("drug")) == bool(attrs.get("material")):
            raise serializers.ValidationError("Informe exatamente um medicamento ou material.")
        return attrs

    def get_affected_patients(self, obj):
        return list(
            self._lots(obj)
            .filter(dispensation_lots__isnull=False)
            .values_list("dispensation_lots__dispensation__patient_id", flat=True)
            .distinct()
        )

    def get_affected_destinations(self, obj):
        return list(
            self._lots(obj)
            .exclude(warehouse=None)
            .values("warehouse_id", "warehouse__code", "quantity")
        )


class DrugSerializer(serializers.ModelSerializer):
    controlled_class_display = serializers.CharField(
        source="get_controlled_class_display", read_only=True
    )
    is_controlled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Drug
        fields = [
            "id",
            "name",
            "generic_name",
            "anvisa_code",
            "barcode",
            "dosage_form",
            "concentration",
            "unit_of_measure",
            "controlled_class",
            "controlled_class_display",
            "is_controlled",
            "min_refill_interval_days",
            "is_active",
            "notes",
            "lead_time_days",
            "safety_stock",
            "reorder_point",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = [
            "id",
            "name",
            "category",
            "barcode",
            "unit_of_measure",
            "is_active",
            "notes",
            "lead_time_days",
            "safety_stock",
            "reorder_point",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class StockItemSerializer(serializers.ModelSerializer):
    drug_name = serializers.CharField(source="drug.name", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()

    class Meta:
        model = StockItem
        fields = [
            "id",
            "drug",
            "drug_name",
            "material",
            "material_name",
            "lot_number",
            "expiry_date",
            "quantity",
            "min_stock",
            "location",
            "warehouse",
            "storage_location",
            "status",
            "is_expired",
            "is_low_stock",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "quantity", "created_at", "updated_at"]

    def get_is_expired(self, obj):
        from django.utils import timezone

        if obj.expiry_date:
            return obj.expiry_date < timezone.now().date()
        return False

    def get_is_low_stock(self, obj):
        return obj.quantity <= obj.min_stock

    def validate(self, attrs):
        warehouse = attrs.get("warehouse", getattr(self.instance, "warehouse", None))
        location = attrs.get("storage_location", getattr(self.instance, "storage_location", None))
        if location and location.warehouse_id != getattr(warehouse, "id", None):
            raise serializers.ValidationError(
                {"storage_location": "A localização deve pertencer ao almoxarifado informado."}
            )
        return attrs


class StockMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(
        source="get_movement_type_display", read_only=True
    )
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "stock_item",
            "movement_type",
            "movement_type_display",
            "quantity",
            "reference",
            "notes",
            "performed_by",
            "performed_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return obj.performed_by.full_name or obj.performed_by.email
        return None

    def validate(self, attrs):
        movement_type = attrs.get("movement_type")
        stock_item = attrs.get("stock_item")
        from django.utils import timezone

        # Dispense movements must only be created through DispenseView (FEFO + Rx gate)
        if movement_type == "dispense":
            raise serializers.ValidationError(
                {"movement_type": "Dispensações devem ser registradas via /pharmacy/dispense/."}
            )
        if movement_type == "purchase_order_receiving":
            raise serializers.ValidationError(
                {
                    "movement_type": "Recebimentos de PO devem ser registrados via /pharmacy/purchase-orders/{id}/receive/."
                }
            )
        if movement_type == "adjustment":
            raise serializers.ValidationError(
                {"movement_type": "Ajustes exigem inventário com aprovação maker-checker."}
            )
        # Validate expiry_date for entries
        if movement_type == "entry" and stock_item and stock_item.expiry_date:
            if stock_item.expiry_date < timezone.now().date():
                raise serializers.ValidationError(
                    {"expiry_date": "Lote já vencido não pode ser adicionado ao estoque."}
                )
        return attrs


class DispensationLotSerializer(serializers.ModelSerializer):
    lot_number = serializers.CharField(source="stock_item.lot_number", read_only=True)
    expiry_date = serializers.DateField(source="stock_item.expiry_date", read_only=True)

    class Meta:
        model = DispensationLot
        fields = ["id", "stock_item", "lot_number", "expiry_date", "quantity"]
        read_only_fields = ["id"]


class DispensationSerializer(serializers.ModelSerializer):
    lots = DispensationLotSerializer(many=True, read_only=True)
    total_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    dispensed_by_name = serializers.SerializerMethodField()
    drug_name = serializers.SerializerMethodField()

    class Meta:
        model = Dispensation
        fields = [
            "id",
            "prescription",
            "prescription_item",
            "patient",
            "dispensed_by",
            "dispensed_by_name",
            "drug_name",
            "notes",
            "dispensed_at",
            "lots",
            "total_quantity",
        ]
        read_only_fields = ["id", "dispensed_at", "dispensed_by"]

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
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    notes = serializers.CharField(required=False, allow_blank=True, default="")


# ─── S-042: Purchase Orders ───────────────────────────────────────────────────


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = (
            "id",
            "name",
            "cnpj",
            "contact_name",
            "contact_email",
            "contact_phone",
            "is_active",
        )
        read_only_fields = ("id",)


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    drug_name = serializers.CharField(source="drug.name", read_only=True, default=None)
    material_name = serializers.CharField(source="material.name", read_only=True, default=None)

    class Meta:
        model = PurchaseOrderItem
        fields = (
            "id",
            "drug",
            "drug_name",
            "material",
            "material_name",
            "quantity_ordered",
            "quantity_received",
            "unit_price",
        )
        read_only_fields = ("id", "quantity_received")

    def validate(self, data):
        drug = data.get("drug")
        material = data.get("material")
        if drug and material:
            raise serializers.ValidationError(
                "Um item de pedido de compra deve ter medicamento OU material, não ambos."
            )
        if not drug and not material:
            raise serializers.ValidationError(
                "Um item de pedido de compra deve ter medicamento ou material."
            )
        return data


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, required=False, default=[])
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "supplier",
            "supplier_name",
            "status",
            "expected_date",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
            "items",
            "item_count",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at", "item_count")

    def get_item_count(self, obj):
        # Use pre-annotated count when available (avoids N+1 on list endpoint)
        if hasattr(obj, "item_count"):
            return obj.item_count
        return obj.items.count()

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        po = PurchaseOrder.objects.create(**validated_data)
        for item_data in items_data:
            PurchaseOrderItem.objects.create(po=po, **item_data)
        return po


class POReceiveItemSerializer(serializers.Serializer):
    """Input for each item in the receive action."""

    item_id = serializers.UUIDField()
    quantity_received = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    lot_number = serializers.CharField(required=False, allow_blank=True, default="")
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)


# ─── S29-02: DoseRule Curation ────────────────────────────────────────────────


class DoseRuleSerializer(serializers.ModelSerializer):
    """Read-only serializer for DoseRule curation list.

    INVIOLABLE: `validated` is exposed as read-only here. The only mutation path
    is through the DoseRuleViewSet.validate action — never through serializer writes.
    """

    drug_name = serializers.CharField(source="formulary.drug.name", read_only=True)
    validated_by = serializers.SerializerMethodField()

    class Meta:
        model = DoseRule
        fields = [
            "id",
            "drug_name",
            "basis",
            "dose_unit",
            "min_per_kg",
            "max_per_kg",
            "min_per_dose",
            "max_per_dose",
            "absolute_max_dose",
            "active",
            "validated",
            "validated_by",
            "validated_at",
        ]
        # All fields are read-only — this serializer is never used for writes.
        read_only_fields = fields

    def get_validated_by(self, obj):
        if obj.validated_by_id is None:
            return None
        user = obj.validated_by
        full_name = (
            getattr(user, "full_name", None) or getattr(user, "get_full_name", lambda: None)()
        )
        return full_name or user.email


# ─── S29-03: AllergenClass & DrugInteraction Curation ────────────────────────


class AllergenClassSerializer(serializers.ModelSerializer):
    """Read-only serializer for AllergenClass curation list.

    INVIOLABLE: `active` is exposed as read-only here. The only mutation path is
    through the AllergenClassViewSet.set_active action — never through serializer writes.
    """

    class Meta:
        model = AllergenClass
        fields = [
            "id",
            "name",
            "members",
            "description",
            "active",
            "source",
            "version",
        ]
        # All fields are read-only — this serializer is never used for writes.
        read_only_fields = fields


class DrugInteractionSerializer(serializers.ModelSerializer):
    """Read-only serializer for DrugInteraction curation list.

    INVIOLABLE: `active` is exposed as read-only here. The only mutation path is
    through the DrugInteractionViewSet.set_active action — never through serializer writes.
    """

    severity_display = serializers.CharField(source="get_severity_display", read_only=True)

    class Meta:
        model = DrugInteraction
        fields = [
            "id",
            "ingredient_a",
            "ingredient_b",
            "severity",
            "severity_display",
            "active",
            "source",
            "version",
        ]
        # All fields are read-only — this serializer is never used for writes.
        read_only_fields = fields


class POReceiveSerializer(serializers.Serializer):
    """Input for POST /pharmacy/purchase-orders/{id}/receive/"""

    items = POReceiveItemSerializer(many=True, min_length=1)  # type: ignore[call-arg]

    def validate_items(self, value):
        ids = [str(item["item_id"]) for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "item_id duplicado: cada item só pode aparecer uma vez por recebimento."
            )
        return value
