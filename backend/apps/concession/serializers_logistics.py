"""DRF serializers for the concession logistics surface."""

from __future__ import annotations

from rest_framework import serializers

from .logistics_models import (
    Dispatch,
    DispatchDiscrepancy,
    DispatchItem,
    PickItem,
    PickList,
    ProofOfDelivery,
    RequisitionItem,
    SupplyRequisition,
)


class RequisitionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequisitionItem
        fields = ["id", "material", "quantity"]


class SupplyRequisitionSerializer(serializers.ModelSerializer):
    items = RequisitionItemSerializer(many=True)

    class Meta:
        model = SupplyRequisition
        fields = [
            "id",
            "requesting_facility",
            "status",
            "requested_by",
            "notes",
            "items",
            "submitted_at",
            "approved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "requested_by",
            "submitted_at",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        requisition = SupplyRequisition.objects.create(**validated_data)
        for item in items:
            RequisitionItem.objects.create(requisition=requisition, **item)
        return requisition


class PickItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickItem
        fields = [
            "id",
            "requisition_item",
            "material",
            "source_stock_item",
            "quantity",
            "picked_qty",
            "is_picked",
            "picked_at",
        ]
        read_only_fields = fields


class PickListSerializer(serializers.ModelSerializer):
    items = PickItemSerializer(many=True, read_only=True)

    class Meta:
        model = PickList
        fields = [
            "id",
            "requisition",
            "status",
            "items",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = ["status", "started_at", "completed_at", "created_at"]


class DispatchItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchItem
        fields = ["id", "material", "source_stock_item", "quantity", "received_qty"]
        read_only_fields = fields


class DispatchSerializer(serializers.ModelSerializer):
    items = DispatchItemSerializer(many=True, read_only=True)

    class Meta:
        model = Dispatch
        fields = [
            "id",
            "manifest_code",
            "pick_list",
            "source_warehouse",
            "destination_facility",
            "destination_warehouse",
            "status",
            "items",
            "shipped_at",
            "delivered_at",
            "created_at",
        ]
        read_only_fields = [
            "destination_facility",
            "status",
            "shipped_at",
            "delivered_at",
            "created_at",
        ]


class DispatchDiscrepancySerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchDiscrepancy
        fields = ["id", "dispatch_item", "type", "material", "quantity", "notes"]


class ProofOfDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProofOfDelivery
        fields = [
            "id",
            "dispatch",
            "received_by",
            "signature_ref",
            "geo_lat",
            "geo_lng",
            "delivered_at",
            "captured_by",
            "created_at",
        ]
        read_only_fields = ["captured_by", "created_at"]


class DeliveryInputSerializer(serializers.Serializer):
    """Payload for the dispatch ``deliver`` action (proof + discrepancies)."""

    received_by = serializers.CharField(max_length=200)
    signature_ref = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )
    geo_lat = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )
    geo_lng = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )
    delivered_at = serializers.DateTimeField(required=False)
    discrepancies = DispatchDiscrepancySerializer(many=True, required=False)
