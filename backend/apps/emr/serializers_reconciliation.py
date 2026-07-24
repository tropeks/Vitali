"""Sprint M1-S3 — serializers for reconciliation + order-set surfaces.

Mirrors EMR serializer conventions: display fields for choices, id/timestamps
read-only, nested writable child items on the aggregate root (reconciliation
items / order-set items) so a whole reconciliation or order set is created in one
POST.
"""

from rest_framework import serializers

from .reconciliation_models import (
    AppliedOrder,
    MedicationReconciliation,
    MedicationReconciliationItem,
    OrderSet,
    OrderSetApplication,
    OrderSetItem,
)


class MedicationReconciliationItemSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = MedicationReconciliationItem
        fields = [
            "id",
            "medication_name",
            "home_dosage",
            "action",
            "action_display",
            "prescription_item",
            "reason",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class MedicationReconciliationSerializer(serializers.ModelSerializer):
    items = MedicationReconciliationItemSerializer(many=True, required=False)
    moment_display = serializers.CharField(source="get_moment_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MedicationReconciliation
        fields = [
            "id",
            "patient",
            "encounter",
            "moment",
            "moment_display",
            "status",
            "status_display",
            "author",
            "notes",
            "items",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = ["id", "status", "author", "created_at", "updated_at", "completed_at"]

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        reconciliation = MedicationReconciliation.objects.create(**validated_data)
        for item in items:
            MedicationReconciliationItem.objects.create(reconciliation=reconciliation, **item)
        return reconciliation


class OrderSetItemSerializer(serializers.ModelSerializer):
    order_type_display = serializers.CharField(source="get_order_type_display", read_only=True)

    class Meta:
        model = OrderSetItem
        fields = [
            "id",
            "order_type",
            "order_type_display",
            "label",
            "drug",
            "dosage_instructions",
            "quantity",
            "details",
            "sequence",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class OrderSetSerializer(serializers.ModelSerializer):
    items = OrderSetItemSerializer(many=True, required=False)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = OrderSet
        fields = [
            "id",
            "key",
            "name",
            "version",
            "status",
            "status_display",
            "description",
            "approval",
            "items",
            "created_by",
            "created_at",
            "updated_at",
            "approved_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "approval",
            "created_by",
            "created_at",
            "updated_at",
            "approved_at",
        ]

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        order_set = OrderSet.objects.create(**validated_data)
        for item in items:
            OrderSetItem.objects.create(order_set=order_set, **item)
        return order_set


class AppliedOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppliedOrder
        fields = [
            "id",
            "encounter",
            "source_item",
            "order_type",
            "label",
            "drug",
            "details",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class OrderSetApplicationSerializer(serializers.ModelSerializer):
    orders = AppliedOrderSerializer(many=True, read_only=True)

    class Meta:
        model = OrderSetApplication
        fields = ["id", "order_set", "encounter", "applied_by", "applied_at", "orders"]
        read_only_fields = fields
