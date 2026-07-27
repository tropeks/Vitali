"""
C1 — DRF viewsets for the Centro Cirúrgico structure (apps.emr.surgery_models).

Permission split: reads require ``surgery.read``, all writes require
``surgery.manage``, gated per-action via ``get_permissions`` exactly like
``_BedsPermissionMixin``. Each viewset is filterable by its parent/scoping FK.
On ``SurgicalCase`` create, ``created_by`` is stamped from ``request.user``
(never client-set); ``surgeon`` / ``patient`` are client-provided.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .serializers_surgery import (
    OperatingRoomSerializer,
    SurgicalCaseSerializer,
    SurgicalProcedureSerializer,
)
from .views import log_audit

_FACILITY_PARAM = OpenApiParameter(
    "facility", str, description="Filtra por estabelecimento (UUID)."
)
_PATIENT_PARAM = OpenApiParameter("patient", str, description="Filtra por paciente (UUID).")
_STATUS_PARAM = OpenApiParameter("status", str, description="Filtra casos por situação.")
_OR_PARAM = OpenApiParameter("operating_room", str, description="Filtra por sala cirúrgica (UUID).")
_SURGEON_PARAM = OpenApiParameter("surgeon", str, description="Filtra por cirurgião (UUID).")
_CASE_PARAM = OpenApiParameter("case", str, description="Filtra por caso cirúrgico (UUID).")


class _SurgeryPermissionMixin:
    """Read=``surgery.read`` / write=``surgery.manage`` per-action gate."""

    def get_permissions(self):
        read_actions = {"list", "retrieve"}
        permission = "surgery.read" if self.action in read_actions else "surgery.manage"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(parameters=[_FACILITY_PARAM]),
)
class OperatingRoomViewSet(_SurgeryPermissionMixin, viewsets.ModelViewSet):
    """Salas cirúrgicas. Managed by surgery.manage."""

    serializer_class = OperatingRoomSerializer

    def get_queryset(self):
        from .models import OperatingRoom

        qs = OperatingRoom.objects.select_related("facility")
        facility = self.request.query_params.get("facility")
        if facility:
            qs = qs.filter(facility_id=facility)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "surgery_room_create", "OperatingRoom", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM, _STATUS_PARAM, _OR_PARAM, _SURGEON_PARAM]),
)
class SurgicalCaseViewSet(_SurgeryPermissionMixin, viewsets.ModelViewSet):
    """Casos cirúrgicos. ``created_by`` é definido no servidor a partir do usuário."""

    serializer_class = SurgicalCaseSerializer

    def get_queryset(self):
        from .models import SurgicalCase

        qs = SurgicalCase.objects.select_related(
            "patient", "surgeon", "operating_room", "encounter", "admission"
        )
        patient = self.request.query_params.get("patient")
        status = self.request.query_params.get("status")
        operating_room = self.request.query_params.get("operating_room")
        surgeon = self.request.query_params.get("surgeon")
        if patient:
            qs = qs.filter(patient_id=patient)
        if status:
            qs = qs.filter(status=status)
        if operating_room:
            qs = qs.filter(operating_room_id=operating_room)
        if surgeon:
            qs = qs.filter(surgeon_id=surgeon)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_audit(self.request, "surgery_case_create", "SurgicalCase", obj.id)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "surgery_case_update", "SurgicalCase", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_CASE_PARAM]),
)
class SurgicalProcedureViewSet(_SurgeryPermissionMixin, viewsets.ModelViewSet):
    """Procedimentos planejados (TUSS) de um caso cirúrgico."""

    serializer_class = SurgicalProcedureSerializer

    def get_queryset(self):
        from .models import SurgicalProcedure

        qs = SurgicalProcedure.objects.select_related("tuss_code", "case")
        case = self.request.query_params.get("case")
        if case:
            qs = qs.filter(case_id=case)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "surgery_procedure_create", "SurgicalProcedure", obj.id)
