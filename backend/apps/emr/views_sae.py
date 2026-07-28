"""
N2-T3 — DRF viewsets for the executable SAE domain (apps.emr.sae_models).

Permission split (COFEN 736/2024 — diagnóstico/prescrição são privativos do
enfermeiro): reads require ``sae.read``, all writes require ``sae.write``, gated
per-action via ``get_permissions`` exactly like ``NursingAssessmentViewSet``.
Each viewset is filterable by ``?patient=`` / ``?encounter=`` (resolved through
the diagnosis chain where the resource has no direct patient/encounter FK) plus
its own parent FK. ``patient`` is derived from the encounter and ``created_by``
is stamped from the request user on create — neither is client-settable.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .serializers_sae import (
    NursingCareplanInterventionSerializer,
    NursingCareplanSerializer,
    NursingDiagnosisSerializer,
    NursingEvolutionSerializer,
    NursingPrescriptionItemSerializer,
)
from .views import log_audit

_PATIENT_PARAM = OpenApiParameter("patient", str, description="Filtra por paciente (UUID).")
_ENCOUNTER_PARAM = OpenApiParameter("encounter", str, description="Filtra por atendimento (UUID).")


class _SaePermissionMixin:
    """Read=``sae.read`` / write=``sae.write`` per-action gate (COFEN 736/2024)."""

    def get_permissions(self):
        permission = "sae.read" if self.action in {"list", "retrieve"} else "sae.write"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM, _ENCOUNTER_PARAM]),
)
class NursingDiagnosisViewSet(_SaePermissionMixin, viewsets.ModelViewSet):
    """Nursing diagnoses (NANDA). Writes are enfermeiro-privativo (``sae.write``)."""

    serializer_class = NursingDiagnosisSerializer

    def get_queryset(self):
        qs = NursingDiagnosis_qs()
        patient = self.request.query_params.get("patient")
        encounter = self.request.query_params.get("encounter")
        if patient:
            qs = qs.filter(patient_id=patient)
        if encounter:
            qs = qs.filter(encounter_id=encounter)
        return qs

    def perform_create(self, serializer):
        encounter = serializer.validated_data["encounter"]
        obj = serializer.save(patient=encounter.patient, created_by=self.request.user)
        log_audit(self.request, "sae_diagnosis_create", "NursingDiagnosis", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM, _ENCOUNTER_PARAM]),
)
class NursingCareplanViewSet(_SaePermissionMixin, viewsets.ModelViewSet):
    """Care plans: expected NOC outcome + target for a diagnosis."""

    serializer_class = NursingCareplanSerializer

    def get_queryset(self):
        from .models import NursingCareplan

        qs = NursingCareplan.objects.select_related("diagnosis", "noc", "created_by")
        diagnosis = self.request.query_params.get("diagnosis")
        patient = self.request.query_params.get("patient")
        encounter = self.request.query_params.get("encounter")
        if diagnosis:
            qs = qs.filter(diagnosis_id=diagnosis)
        if patient:
            qs = qs.filter(diagnosis__patient_id=patient)
        if encounter:
            qs = qs.filter(diagnosis__encounter_id=encounter)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_audit(self.request, "sae_careplan_create", "NursingCareplan", obj.id)


class NursingCareplanInterventionViewSet(_SaePermissionMixin, viewsets.ModelViewSet):
    """NIC interventions attached to a care plan (careplan 1—* NIC)."""

    serializer_class = NursingCareplanInterventionSerializer

    def get_queryset(self):
        from .models import NursingCareplanIntervention

        qs = NursingCareplanIntervention.objects.select_related("careplan", "nic")
        careplan = self.request.query_params.get("careplan")
        patient = self.request.query_params.get("patient")
        if careplan:
            qs = qs.filter(careplan_id=careplan)
        if patient:
            qs = qs.filter(careplan__diagnosis__patient_id=patient)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "sae_intervention_create", "NursingCareplanIntervention", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM]),
)
class NursingPrescriptionItemViewSet(_SaePermissionMixin, viewsets.ModelViewSet):
    """Executable nursing prescription lines (drive aprazamento). Enfermeiro-privativo."""

    serializer_class = NursingPrescriptionItemSerializer

    def get_queryset(self):
        from .models import NursingPrescriptionItem

        qs = NursingPrescriptionItem.objects.select_related("intervention", "created_by")
        intervention = self.request.query_params.get("intervention")
        patient = self.request.query_params.get("patient")
        encounter = self.request.query_params.get("encounter")
        if intervention:
            qs = qs.filter(intervention_id=intervention)
        if patient:
            qs = qs.filter(intervention__careplan__diagnosis__patient_id=patient)
        if encounter:
            qs = qs.filter(intervention__careplan__diagnosis__encounter_id=encounter)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_audit(self.request, "sae_prescription_create", "NursingPrescriptionItem", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM, _ENCOUNTER_PARAM]),
)
class NursingEvolutionViewSet(_SaePermissionMixin, viewsets.ModelViewSet):
    """Nursing evolution notes (evolução)."""

    serializer_class = NursingEvolutionSerializer

    def get_queryset(self):
        from .models import NursingEvolution

        qs = NursingEvolution.objects.select_related("patient", "encounter", "created_by")
        patient = self.request.query_params.get("patient")
        encounter = self.request.query_params.get("encounter")
        if patient:
            qs = qs.filter(patient_id=patient)
        if encounter:
            qs = qs.filter(encounter_id=encounter)
        return qs

    def perform_create(self, serializer):
        encounter = serializer.validated_data["encounter"]
        obj = serializer.save(patient=encounter.patient, created_by=self.request.user)
        log_audit(self.request, "sae_evolution_create", "NursingEvolution", obj.id)


def NursingDiagnosis_qs():
    """Base queryset for diagnoses (import-local to avoid model import at module load)."""
    from .models import NursingDiagnosis

    return NursingDiagnosis.objects.select_related("patient", "encounter", "nanda", "created_by")
