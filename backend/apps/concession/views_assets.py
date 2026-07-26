"""C1 — Gated REST viewsets for the comodato fleet.

Every viewset is tier-gated on ``ConcessionModule`` (the tenant must have the
``diagnostic_concession`` FeatureFlag active) and writes an audit trail via the
local ``log_audit`` helper (mirrors pharmacy/emr).
"""

import json

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import AuditLog

from .asset_models import AssetMovement, AssetService, EquipmentAsset, MaintenanceTicket
from .permissions import ConcessionModule
from .serializers_assets import (
    AssetMovementSerializer,
    AssetServiceSerializer,
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


@extend_schema_view(
    list=extend_schema(responses=AssetServiceSerializer(many=True)),
    retrieve=extend_schema(responses=AssetServiceSerializer),
    create=extend_schema(request=AssetServiceSerializer, responses=AssetServiceSerializer),
    update=extend_schema(request=AssetServiceSerializer, responses=AssetServiceSerializer),
    partial_update=extend_schema(request=AssetServiceSerializer, responses=AssetServiceSerializer),
    destroy=extend_schema(responses={204: None}),
)
class AssetServiceViewSet(viewsets.ModelViewSet):
    """B0-T2 — which services/exams an asset enables (asset → enabled exams).

    Filter by ``?asset=<id>`` to list the exams a given equipment enables.
    """

    queryset = AssetService.objects.select_related("asset", "service").all()
    serializer_class = AssetServiceSerializer
    permission_classes = [IsAuthenticated, ConcessionModule]

    def get_queryset(self):
        qs = AssetService.objects.select_related("asset", "service").all()
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        service_id = self.request.query_params.get("service")
        if service_id:
            qs = qs.filter(service_id=service_id)
        return qs

    def perform_create(self, serializer):
        link = serializer.save()
        log_audit(self.request, "create", "AssetService", link.id, new_data=serializer.data)

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "AssetService", instance.id)
        instance.delete()


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

    @extend_schema(
        request=inline_serializer(
            name="MaintenanceTicketStartInput",
            fields={"assigned_to": serializers.IntegerField(required=False)},
        ),
        responses=MaintenanceTicketSerializer,
    )
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """B0-T5 — OPEN → IN_PROGRESS; keeps the asset IN_MAINTENANCE."""
        from apps.core.models import User

        ticket = self.get_object()
        assigned_to = None
        assigned_id = request.data.get("assigned_to")
        if assigned_id:
            assigned_to = User.objects.filter(pk=assigned_id).first()
        ticket.start(assigned_to=assigned_to)
        log_audit(request, "start", "MaintenanceTicket", ticket.id)
        return Response(self.get_serializer(ticket).data)

    @extend_schema(
        request=inline_serializer(
            name="MaintenanceTicketCompleteInput",
            fields={
                "resolution": serializers.CharField(required=False, allow_blank=True),
                "cost": serializers.DecimalField(max_digits=12, decimal_places=2, required=False),
            },
        ),
        responses=MaintenanceTicketSerializer,
    )
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """B0-T5 — → COMPLETED; frees the asset back to ACTIVE and records cost."""
        ticket = self.get_object()
        cost = request.data.get("cost")
        ticket.complete(resolution=request.data.get("resolution", ""), cost=cost)
        log_audit(request, "complete", "MaintenanceTicket", ticket.id, new_data={"cost": str(cost)})
        return Response(self.get_serializer(ticket).data)
