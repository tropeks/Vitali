"""
L1 — DRF viewsets for the ADT/Leitos bed structure (apps.emr.adt_models).

Permission split: reads require ``beds.read``, all writes require ``beds.manage``
(NIR/Gestão de Leitos gere a estrutura), gated per-action via ``get_permissions``
exactly like ``NursingDiagnosisViewSet``. Each viewset is filterable by its parent
FK. On ``Bed`` create/update the denormalized ``unit`` FK is derived from the room
(never client-set) so per-unit census queries stay consistent.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .serializers_adt import BedSerializer, InpatientUnitSerializer, RoomSerializer
from .views import log_audit

_FACILITY_PARAM = OpenApiParameter(
    "facility", str, description="Filtra por estabelecimento (UUID)."
)
_UNIT_PARAM = OpenApiParameter("unit", str, description="Filtra por unidade de internação (UUID).")
_ROOM_PARAM = OpenApiParameter("room", str, description="Filtra por quarto (UUID).")
_STATUS_PARAM = OpenApiParameter("status", str, description="Filtra leitos por situação.")


class _BedsPermissionMixin:
    """Read=``beds.read`` / write=``beds.manage`` per-action gate."""

    def get_permissions(self):
        permission = "beds.read" if self.action in {"list", "retrieve"} else "beds.manage"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(parameters=[_FACILITY_PARAM]),
)
class InpatientUnitViewSet(_BedsPermissionMixin, viewsets.ModelViewSet):
    """Inpatient units (ala/unidade de internação). Managed by beds.manage."""

    serializer_class = InpatientUnitSerializer

    def get_queryset(self):
        from .models import InpatientUnit

        qs = InpatientUnit.objects.select_related("facility", "default_bed_type")
        facility = self.request.query_params.get("facility")
        if facility:
            qs = qs.filter(facility_id=facility)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "beds_unit_create", "InpatientUnit", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_UNIT_PARAM]),
)
class RoomViewSet(_BedsPermissionMixin, viewsets.ModelViewSet):
    """Rooms (quarto) inside an inpatient unit."""

    serializer_class = RoomSerializer

    def get_queryset(self):
        from .models import Room

        qs = Room.objects.select_related("unit")
        unit = self.request.query_params.get("unit")
        if unit:
            qs = qs.filter(unit_id=unit)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "beds_room_create", "Room", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_UNIT_PARAM, _ROOM_PARAM, _STATUS_PARAM]),
)
class BedViewSet(_BedsPermissionMixin, viewsets.ModelViewSet):
    """Physical beds (leito). ``unit`` is derived from the room server-side."""

    serializer_class = BedSerializer

    def get_queryset(self):
        from .models import Bed

        qs = Bed.objects.select_related("room", "unit", "bed_type")
        unit = self.request.query_params.get("unit")
        room = self.request.query_params.get("room")
        status = self.request.query_params.get("status")
        if unit:
            qs = qs.filter(unit_id=unit)
        if room:
            qs = qs.filter(room_id=room)
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        room = serializer.validated_data["room"]
        obj = serializer.save(unit=room.unit)
        log_audit(self.request, "beds_bed_create", "Bed", obj.id)

    def perform_update(self, serializer):
        # Keep the denormalized ``unit`` FK consistent if the room changes.
        room = serializer.validated_data.get("room")
        if room is not None:
            obj = serializer.save(unit=room.unit)
        else:
            obj = serializer.save()
        log_audit(self.request, "beds_bed_update", "Bed", obj.id)
