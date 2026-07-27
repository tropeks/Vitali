"""
C1 — DRF viewsets for the Centro Cirúrgico structure (apps.emr.surgery_models).

Permission split: reads require ``surgery.read``, all writes require
``surgery.manage``, gated per-action via ``get_permissions`` exactly like
``_BedsPermissionMixin``. Each viewset is filterable by its parent/scoping FK.
On ``SurgicalCase`` create, ``created_by`` is stamped from ``request.user``
(never client-set); ``surgeon`` / ``patient`` are client-provided.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .serializers_surgery import (
    OperatingRoomSerializer,
    SurgicalCaseCancelSerializer,
    SurgicalCaseRescheduleSerializer,
    SurgicalCaseScheduleSerializer,
    SurgicalCaseSerializer,
    SurgicalProcedureSerializer,
)
from .services import surgery_scheduling as scheduling_service
from .views import log_audit

_FACILITY_PARAM = OpenApiParameter(
    "facility", str, description="Filtra por estabelecimento (UUID)."
)
_PATIENT_PARAM = OpenApiParameter("patient", str, description="Filtra por paciente (UUID).")
_STATUS_PARAM = OpenApiParameter("status", str, description="Filtra casos por situação.")
_OR_PARAM = OpenApiParameter("operating_room", str, description="Filtra por sala cirúrgica (UUID).")
_SURGEON_PARAM = OpenApiParameter("surgeon", str, description="Filtra por cirurgião (UUID).")
_CASE_PARAM = OpenApiParameter("case", str, description="Filtra por caso cirúrgico (UUID).")
_DATE_PARAM = OpenApiParameter("date", str, description="Data do mapa cirúrgico (YYYY-MM-DD).")


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
    """Casos cirúrgicos. ``created_by`` é definido no servidor a partir do usuário.

    Per-action gate (overrides ``_SurgeryPermissionMixin``):

    * ``list`` / ``retrieve`` / ``board`` → ``surgery.read``
    * ``schedule`` / ``reschedule`` / ``confirm`` / ``cancel`` → ``surgery.schedule``
      (all lifecycle/slot transitions require the scheduling capability)
    * everything else (create / update / destroy) → ``surgery.manage``
    """

    serializer_class = SurgicalCaseSerializer

    def get_permissions(self):
        read_actions = {"list", "retrieve", "board"}
        schedule_actions = {"schedule", "reschedule", "confirm", "cancel"}
        if self.action in read_actions:
            permission = "surgery.read"
        elif self.action in schedule_actions:
            permission = "surgery.schedule"
        else:
            permission = "surgery.manage"
        return [IsAuthenticated(), HasPermission(permission)]

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

    # ── C2: scheduling lifecycle (through the atomic service; overlap → 409) ────

    @extend_schema(request=SurgicalCaseScheduleSerializer, responses=SurgicalCaseSerializer)
    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """Agenda o caso numa sala + janela de horário. Conflito de agenda → 409."""
        case = self.get_object()
        payload = SurgicalCaseScheduleSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            case = scheduling_service.schedule(
                case,
                payload.validated_data["operating_room"],
                payload.validated_data["scheduled_start"],
                payload.validated_data["scheduled_end"],
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "surgery_case_schedule", "SurgicalCase", case.id)
        return Response(self.get_serializer(case).data)

    @extend_schema(request=SurgicalCaseRescheduleSerializer, responses=SurgicalCaseSerializer)
    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        """Reagenda o caso (nova janela e, opcionalmente, nova sala). Conflito → 409."""
        case = self.get_object()
        payload = SurgicalCaseRescheduleSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            case = scheduling_service.reschedule(
                case,
                payload.validated_data["scheduled_start"],
                payload.validated_data["scheduled_end"],
                operating_room=payload.validated_data.get("operating_room"),
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "surgery_case_reschedule", "SurgicalCase", case.id)
        return Response(self.get_serializer(case).data)

    @extend_schema(request=None, responses=SurgicalCaseSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Confirma um caso agendado (agendada → confirmada). Transição inválida → 409."""
        case = self.get_object()
        try:
            case = scheduling_service.confirm(case, actor=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "surgery_case_confirm", "SurgicalCase", case.id)
        return Response(self.get_serializer(case).data)

    @extend_schema(request=SurgicalCaseCancelSerializer, responses=SurgicalCaseSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancela o caso (→ cancelada; libera o slot da sala). Transição inválida → 409."""
        case = self.get_object()
        payload = SurgicalCaseCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            case = scheduling_service.cancel(
                case, reason=payload.validated_data.get("reason", ""), actor=request.user
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "surgery_case_cancel", "SurgicalCase", case.id)
        return Response(self.get_serializer(case).data)

    @extend_schema(
        parameters=[_DATE_PARAM, _OR_PARAM, _FACILITY_PARAM],
        responses=OpenApiTypes.OBJECT,
        description="Mapa cirúrgico: salas (de um estabelecimento) com seus casos "
        "agendados para uma data. Gated surgery.read.",
    )
    @action(detail=False, methods=["get"])
    def board(self, request):
        """Surgical board: rooms × their scheduled cases for a date.

        Rooms are those of the ``facility`` (and/or a single ``operating_room``).
        Cases are the non-cancelled ones whose ``scheduled_start`` falls on
        ``date`` (defaults to today). Each case carries patient, surgeon,
        window, status, priority and a procedures summary. Ids are stringified
        (client-facing contract, like the ADT board)."""
        from datetime import date as _date

        from django.utils import timezone

        from .models import OperatingRoom, SurgicalCase

        raw_date = request.query_params.get("date")
        if raw_date:
            board_date = _date.fromisoformat(raw_date)
        else:
            board_date = timezone.localdate()

        rooms_qs = OperatingRoom.objects.all()
        facility = request.query_params.get("facility")
        operating_room = request.query_params.get("operating_room")
        if facility:
            rooms_qs = rooms_qs.filter(facility_id=facility)
        if operating_room:
            rooms_qs = rooms_qs.filter(id=operating_room)
        rooms_qs = rooms_qs.order_by("code")

        cases_qs = (
            SurgicalCase.objects.filter(
                operating_room__in=rooms_qs,
                scheduled_start__date=board_date,
            )
            .exclude(status=SurgicalCase.Status.CANCELADA)
            .select_related("patient", "surgeon", "surgeon__user")
            .prefetch_related("procedures", "procedures__tuss_code")
            .order_by("scheduled_start")
        )

        cases_by_room: dict = {}
        for case in cases_qs:
            cases_by_room.setdefault(case.operating_room_id, []).append(
                {
                    "id": str(case.id),
                    "patient": {"id": str(case.patient_id), "name": case.patient.full_name},
                    "surgeon": {
                        "id": str(case.surgeon_id),
                        "name": case.surgeon.user.full_name,
                    },
                    "scheduled_start": case.scheduled_start,
                    "scheduled_end": case.scheduled_end,
                    "status": case.status,
                    "priority": case.priority,
                    "procedures": [
                        {
                            "tuss_code": proc.tuss_code_value,
                            "description": (
                                proc.tuss_code.description if proc.tuss_code_id else ""
                            ),
                            "quantity": proc.quantity,
                        }
                        for proc in case.procedures.all()
                    ],
                }
            )

        rooms_out = [
            {
                "id": str(room.id),
                "code": room.code,
                "name": room.name,
                "cases": cases_by_room.get(room.id, []),
            }
            for room in rooms_qs
        ]
        return Response({"date": board_date.isoformat(), "rooms": rooms_out})


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
