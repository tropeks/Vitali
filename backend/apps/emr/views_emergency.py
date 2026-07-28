"""
E2 — DRF viewsets for the PS/Emergência domain (apps.emr.emergency_models).

Permission split (per-action, mirroring ``_BedsPermissionMixin`` /
``SurgicalCaseViewSet``):

* boletim reads (list/retrieve) → ``emergency.read``; writes (create/update/…)
  → ``emergency.manage``.
* the ``classify`` action → ``emergency.classify`` (the classificador
  capability), routed THROUGH ``apps.emr.services.emergency_classify`` so the
  acuity snapshot + append-only history + status advance stay atomic.
* risk-classifications is read-only (append-only history) → ``emergency.read``.
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

from .serializers_emergency import (
    ClassifyInputSerializer,
    CloseInputSerializer,
    EmergencyEncounterSerializer,
    RiskClassificationSerializer,
    StartAttendanceInputSerializer,
)
from .services import emergency_classify as classify_service
from .services import emergency_lifecycle as lifecycle_service
from .services import emergency_queue as queue_service
from .views import log_audit

_FACILITY_PARAM = OpenApiParameter(
    "facility", str, description="Filtra por estabelecimento (UUID) — reservado (E4)."
)


def _serialize_queue_row(row: dict) -> dict:
    """Stringify ids for a queue row (service keeps UUIDs; endpoint emits str)."""
    return {
        "boletim_id": str(row["boletim_id"]),
        "patient": {"id": str(row["patient_id"]), "name": row["patient_name"]},
        "status": row["status"],
        "mode_of_arrival": row["mode_of_arrival"],
        "chief_complaint": row["chief_complaint"],
        "arrival_at": row["arrival_at"],
        "waited_minutes": row["waited_minutes"],
        "acuity_level": row["acuity_level"],
        "target_minutes": row["target_minutes"],
        "overdue": row["overdue"],
    }


_PATIENT_PARAM = OpenApiParameter("patient", str, description="Filtra por paciente (UUID).")
_STATUS_PARAM = OpenApiParameter("status", str, description="Filtra boletins por situação.")
_BOLETIM_PARAM = OpenApiParameter(
    "boletim", str, description="Filtra classificações por boletim (UUID)."
)


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM, _STATUS_PARAM]),
)
class EmergencyEncounterViewSet(viewsets.ModelViewSet):
    """Boletins de emergência (BAE). Reads ``emergency.read`` / writes
    ``emergency.manage``; the ``classify`` action needs ``emergency.classify``."""

    serializer_class = EmergencyEncounterSerializer

    def get_permissions(self):
        read_actions = {"list", "retrieve", "board"}
        if self.action in read_actions:
            permission = "emergency.read"
        elif self.action == "classify":
            permission = "emergency.classify"
        else:
            # writes + lifecycle actions (start_attendance / close)
            permission = "emergency.manage"
        return [IsAuthenticated(), HasPermission(permission)]

    def get_queryset(self):
        from .models import EmergencyEncounter

        qs = EmergencyEncounter.objects.select_related("patient", "encounter", "created_by")
        patient = self.request.query_params.get("patient")
        status = self.request.query_params.get("status")
        if patient:
            qs = qs.filter(patient_id=patient)
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_audit(self.request, "emergency_boletim_create", "EmergencyEncounter", obj.id)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "emergency_boletim_update", "EmergencyEncounter", obj.id)

    @extend_schema(request=ClassifyInputSerializer, responses=EmergencyEncounterSerializer)
    @action(detail=True, methods=["post"])
    def classify(self, request, pk=None):
        """Classifica (triagem Manchester) o boletim com um discriminador — copia
        acuidade/tempo-alvo do catálogo e avança status → classificado. Cada
        chamada anexa uma nova RiskClassification (re-triagem nunca edita)."""
        boletim = self.get_object()
        payload = ClassifyInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        classification = classify_service.classify(
            boletim,
            payload.validated_data["discriminator"],
            vitals=payload.validated_data.get("vitals"),
            by=request.user,
            notes=payload.validated_data.get("notes", ""),
        )
        log_audit(request, "emergency_classify", "RiskClassification", classification.id)
        boletim.refresh_from_db()
        return Response(self.get_serializer(boletim).data, status=http_status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[_FACILITY_PARAM],
        responses=OpenApiTypes.OBJECT,
        description="Painel do PS: fila por gravidade (não classificados primeiro, "
        "depois vermelho→azul, depois chegada) + contagens por acuidade + overdue. "
        "Gated emergency.read.",
    )
    @action(detail=False, methods=["get"])
    def board(self, request):
        """PS board: acuity-ordered queue + counts by acuity level + overdue count."""
        facility = request.query_params.get("facility")
        data = queue_service.board(facility=facility)
        data["queue"] = [_serialize_queue_row(row) for row in data["queue"]]
        return Response(data)

    @extend_schema(request=StartAttendanceInputSerializer, responses=EmergencyEncounterSerializer)
    @action(detail=True, methods=["post"], url_path="start-attendance")
    def start_attendance(self, request, pk=None):
        """Chamar/iniciar atendimento: classificado → em_atendimento. Transição
        ilegal (status ≠ classificado) → 409. Gated emergency.manage."""
        boletim = self.get_object()
        payload = StartAttendanceInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            boletim = lifecycle_service.start_attendance(
                boletim,
                professional=payload.validated_data.get("professional"),
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "emergency_start_attendance", "EmergencyEncounter", boletim.id)
        return Response(self.get_serializer(boletim).data)

    @extend_schema(request=CloseInputSerializer, responses=EmergencyEncounterSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Encerrar o boletim (+ desfecho). Com desfecho=internacao + leito livre,
        aciona a ponte de internação (adt.admit) na mesma transação. Transição
        ilegal / leito ocupado → 409. Gated emergency.manage."""
        boletim = self.get_object()
        payload = CloseInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            boletim = lifecycle_service.close(
                boletim,
                disposition=data["disposition"],
                actor=request.user,
                bed=data.get("bed"),
                admitting_professional=data.get("admitting_professional"),
                attending_professional=data.get("attending_professional"),
                admission_source=data.get("admission_source") or None,
                admission_datetime=data.get("admission_datetime"),
                reason=data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "emergency_close", "EmergencyEncounter", boletim.id)
        return Response(self.get_serializer(boletim).data)


@extend_schema_view(
    list=extend_schema(parameters=[_BOLETIM_PARAM]),
)
class RiskClassificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only append-only risk-classification history. Gated ``emergency.read``."""

    serializer_class = RiskClassificationSerializer

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission("emergency.read")]

    def get_queryset(self):
        from .models import RiskClassification

        qs = RiskClassification.objects.select_related(
            "boletim", "flowchart", "discriminator", "vitals", "classified_by"
        )
        boletim = self.request.query_params.get("boletim")
        if boletim:
            qs = qs.filter(boletim_id=boletim)
        return qs
