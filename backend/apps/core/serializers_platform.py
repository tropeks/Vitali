"""
Platform admin serializers — Plans, PlanModules, Subscriptions.
These models live in the public schema (SHARED_APPS).
Used only by /api/v1/platform/* endpoints (IsPlatformAdmin gate).
"""
from rest_framework import serializers

from .constants import ALLOWED_MODULE_KEYS
from .models import FeatureFlag, Plan, PlanModule, Subscription, Tenant


class PlanModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanModule
        fields = ("id", "module_key", "price", "is_included")


class PlanSerializer(serializers.ModelSerializer):
    modules = PlanModuleSerializer(many=True, read_only=True)

    class Meta:
        model = Plan
        fields = ("id", "name", "base_price", "is_active", "modules", "created_at")
        read_only_fields = ("id", "created_at")


class SubscriptionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "id",
            "tenant_id",
            "tenant_name",
            "plan",
            "plan_name",
            "active_modules",
            "monthly_price",
            "status",
            "current_period_start",
            "current_period_end",
            "created_at",
        )
        read_only_fields = ("id", "tenant_id", "tenant_name", "plan_name", "created_at")

    def validate_active_modules(self, value):
        unknown = set(value) - ALLOWED_MODULE_KEYS
        if unknown:
            raise serializers.ValidationError(
                f"Unknown module keys: {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(sorted(ALLOWED_MODULE_KEYS))}"
            )
        return value


class TenantSubscriptionSerializer(serializers.ModelSerializer):
    """Tenant-facing read-only subscription view (S-041)."""
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_base_price = serializers.DecimalField(
        source="plan.base_price", max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Subscription
        fields = (
            "id",
            "plan_name",
            "plan_base_price",
            "active_modules",
            "monthly_price",
            "status",
            "current_period_start",
            "current_period_end",
        )
        read_only_fields = fields
