"""C1 — Gated REST viewsets for the comodato fleet.

Every viewset is tier-gated on ``ConcessionModule`` (the tenant must have the
``diagnostic_concession`` FeatureFlag active) and writes an audit trail via the
local ``log_audit`` helper (mirrors pharmacy/emr).
"""

import json

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.models import AuditLog

from .asset_models import AssetMovement, EquipmentAsset, MaintenanceTicket
from .permissions import ConcessionModule
from .serializers_assets import (
    AssetMovementSerializer,
    EquipmentAssetSerializer,
    MaintenanceTicketSerializer,
)


def _json_safe(data):
    """Coerce DRF serializer output (UUID/Decimal/date) into JSON-storable types."""
    if data is None:
        return None
    return json.loads(json.dumps(data, default=str))


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=_json_safe(old_data),
        new_data=_json_safe(new_data),
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


class EquipmentAssetViewSet(viewsets.ModelViewSet):
    queryset = EquipmentAsset.objects.all()
    serializer_class = EquipmentAssetSerializer
    permission_classes = [IsAuthenticated, ConcessionModule]

    def perform_create(self, serializer):
        asset = serializer.save()
        log_audit(self.request, "create", "EquipmentAsset", asset.id, new_data=serializer.data)

    def perform_update(self, serializer):
        old = EquipmentAssetSerializer(serializer.instance).data
        asset = serializer.save()
        log_audit(
            self.request,
            "update",
            "EquipmentAsset",
            asset.id,
            old_data=old,
            new_data=serializer.data,
        )

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "EquipmentAsset", instance.id)
        instance.delete()


class AssetMovementViewSet(viewsets.ModelViewSet):
    """Append-only ledger — creation and reads only."""

    queryset = AssetMovement.objects.all()
    serializer_class = AssetMovementSerializer
    permission_classes = [IsAuthenticated, ConcessionModule]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        movement = serializer.save()
        log_audit(self.request, "create", "AssetMovement", movement.id, new_data=serializer.data)


class MaintenanceTicketViewSet(viewsets.ModelViewSet):
    queryset = MaintenanceTicket.objects.all()
    serializer_class = MaintenanceTicketSerializer
    permission_classes = [IsAuthenticated, ConcessionModule]

    def perform_create(self, serializer):
        ticket = serializer.save()
        log_audit(self.request, "create", "MaintenanceTicket", ticket.id, new_data=serializer.data)

    def perform_update(self, serializer):
        old = MaintenanceTicketSerializer(serializer.instance).data
        ticket = serializer.save()
        log_audit(
            self.request,
            "update",
            "MaintenanceTicket",
            ticket.id,
            old_data=old,
            new_data=serializer.data,
        )
