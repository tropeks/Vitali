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

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .serializers_emergency import (
    ClassifyInputSerializer,
    EmergencyEncounterSerializer,
    RiskClassificationSerializer,
)
from .services import emergency_classify as classify_service
from .views import log_audit

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
        read_actions = {"list", "retrieve"}
        if self.action in read_actions:
            permission = "emergency.read"
        elif self.action == "classify":
            permission = "emergency.classify"
        else:
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
