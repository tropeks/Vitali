"""Sprint E2 — REST surface for the problem-oriented EMR models.

Three ModelViewSets (problem list, allergies, immunizations) consistent with the
rest of the EMR API:

* permission split — ``emr.read`` for list/retrieve, ``emr.write`` for writes;
* tenant scoping — implicit (django-tenants routes every query to the caller's
  schema); an optional ``?patient=<uuid>`` narrows to one patient's records;
* audit — every write goes through the shared ``log_audit`` helper.

Deliberately self-contained: NO wiring into pharmacy's dose/interaction checker
here (the parent does that cross-module integration).
"""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .models import Allergy, Immunization, ProblemListItem
from .serializers_problems import (
    AllergyRecordSerializer,
    ImmunizationSerializer,
    ProblemListItemSerializer,
)
from .views import log_audit

_READ_ACTIONS = {"list", "retrieve"}


class _PatientScopedEMRViewSet(viewsets.ModelViewSet):
    """Shared behaviour: emr.read/emr.write split + optional ?patient filter."""

    audit_resource_type = ""
    audit_create_action = ""

    def get_permissions(self):
        permission = "emr.read" if self.action in _READ_ACTIONS else "emr.write"
        return [IsAuthenticated(), HasPermission(permission)]

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get("patient")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        log_audit(
            self.request,
            self.audit_create_action,
            self.audit_resource_type,
            instance.id,
            new_data={"patient": str(instance.patient_id)},
        )


class ProblemListItemViewSet(_PatientScopedEMRViewSet):
    """Patient problem list (FHIR Condition-style)."""

    queryset = ProblemListItem.objects.select_related("patient", "encounter", "cid10").all()
    serializer_class = ProblemListItemSerializer
    audit_resource_type = "ProblemListItem"
    audit_create_action = "problem_create"


class AllergyViewSet(_PatientScopedEMRViewSet):
    """Standalone allergy surface (governed allergen class + coded reaction)."""

    queryset = Allergy.objects.select_related("patient", "allergen_class").all()
    serializer_class = AllergyRecordSerializer
    audit_resource_type = "Allergy"
    audit_create_action = "allergy_create"


class ImmunizationViewSet(_PatientScopedEMRViewSet):
    """Patient immunization history (FHIR Immunization-style)."""

    queryset = Immunization.objects.select_related("patient").all()
    serializer_class = ImmunizationSerializer
    audit_resource_type = "Immunization"
    audit_create_action = "immunization_create"
