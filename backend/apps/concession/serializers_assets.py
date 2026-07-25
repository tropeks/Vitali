"""C1 — DRF serializers for the comodato fleet."""

from rest_framework import serializers

from .asset_models import (
    AssetMovement,
    AssetService,
    EquipmentAsset,
    MaintenanceTicket,
)


class AssetServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetService
        fields = ["id", "asset", "service", "created_at"]
        read_only_fields = ["id", "created_at"]


class EquipmentAssetSerializer(serializers.ModelSerializer):
    monthly_depreciation = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentAsset
        fields = [
            "id",
            "asset_tag",
            "name",
            "model",
            "serial_number",
            "status",
            "ownership",
            "purchase_cost",
            "useful_life_months",
            "purchase_date",
            "current_location",
            "active",
            "monthly_depreciation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_monthly_depreciation(self, obj) -> str:
        return str(obj.monthly_depreciation)


class AssetMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetMovement
        fields = [
            "id",
            "movement_type",
            "asset",
            "from_facility",
            "to_facility",
            "swapped_with",
            "performed_by",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class MaintenanceTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceTicket
        fields = [
            "id",
            "asset",
            "facility",
            "description",
            "status",
            "cost",
            "evidence_url",
            "resolution",
            "reported_by",
            "assigned_to",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
