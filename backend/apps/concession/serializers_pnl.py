"""Sprint C4 — serializers for the P&L surface.

The P&L payload is a computed roll-up (Decimals + a per-service list), returned
as-is by the view. Here we only validate the read query params (period + an
optional single unit) so the endpoint parses ``?start=&end=&unit=`` safely.
"""

from rest_framework import serializers

from apps.organization.models import Facility
from apps.pharmacy.models import Warehouse

from .models import ConcessionService
from .pnl_models import ExamConsumption, MaterialUnitCost


class PnlQuerySerializer(serializers.Serializer):
    """Validate the P&L read query params."""

    start = serializers.DateField(required=False, allow_null=True)
    end = serializers.DateField(required=False, allow_null=True)
    unit = serializers.UUIDField(required=False, allow_null=True)


class MaterialUnitCostSerializer(serializers.ModelSerializer):
    """B0-T3 — the operator's concession-local unit cost for a material."""

    class Meta:
        model = MaterialUnitCost
        fields = ["id", "material", "unit_cost", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ExamConsumptionSerializer(serializers.ModelSerializer):
    """B0-T4 — read view of one append-only consumption ledger row."""

    class Meta:
        model = ExamConsumption
        fields = [
            "id",
            "unit",
            "service",
            "external_ref",
            "dicom_study",
            "source_warehouse",
            "performed_at",
            "cost_snapshot",
            "idempotency_key",
            "created_at",
        ]
        read_only_fields = fields


class ExamConsumptionRecordSerializer(serializers.Serializer):
    """B0-T4 — validate the manual (non-DICOM) consumption record payload.

    Delegates to ``services_pnl.record_exam_consumption``; an ``external_ref`` is
    required (the manual analog of a DICOM study's identity)."""

    service = serializers.PrimaryKeyRelatedField(queryset=ConcessionService.objects.all())
    unit = serializers.PrimaryKeyRelatedField(queryset=Facility.objects.all())
    external_ref = serializers.CharField(max_length=128)
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.objects.all(), required=False, allow_null=True
    )
    performed_at = serializers.DateTimeField(required=False, allow_null=True)
