"""Sprint C2 — serializers for contract / price / recipe."""

from rest_framework import serializers

from .contract_models import (
    ConcessionContract,
    ContractServicePrice,
    ServiceRecipe,
)


class ConcessionContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConcessionContract
        fields = [
            "id",
            "name",
            "client_name",
            "client",
            "units",
            "monthly_value",
            "start_date",
            "end_date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ContractServicePriceSerializer(serializers.ModelSerializer):
    billable_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ContractServicePrice
        fields = [
            "id",
            "contract",
            "unit",
            "service",
            "price",
            "is_billable",
            "billable_revenue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "billable_revenue", "created_at", "updated_at"]


class ServiceRecipeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceRecipe
        fields = [
            "id",
            "service",
            "material",
            "quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
