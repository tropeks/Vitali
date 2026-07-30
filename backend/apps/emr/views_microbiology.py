from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission

from .models import AntibiogramEntry, IsolatedOrganism, MicrobiologyResult
from .serializers_microbiology import (
    AntibiogramEntrySerializer,
    IsolatedOrganismSerializer,
    MicrobiologyResultSerializer,
)


class MicrobiologyPermissionsMixin:
    """Mirror of the LIS diagnostics RBAC: read for list/retrieve, write else."""

    def get_permissions(self):
        permission = "emr.read" if self.action in {"list", "retrieve"} else "emr.write"
        return [IsAuthenticated(), HasPermission(permission)]


class MicrobiologyResultViewSet(MicrobiologyPermissionsMixin, viewsets.ModelViewSet):
    serializer_class = MicrobiologyResultSerializer

    def get_queryset(self):
        qs = MicrobiologyResult.objects.select_related("order_item", "created_by").prefetch_related(
            "organisms__antibiogram"
        )
        order_item = self.request.query_params.get("order_item")
        if order_item:
            qs = qs.filter(order_item_id=order_item)
        # Patient-scoped view (prontuário): all micro results of a patient across
        # their lab orders (order_item → order → patient).
        patient = self.request.query_params.get("patient")
        if patient:
            qs = qs.filter(order_item__order__patient_id=patient)
        culture_result = self.request.query_params.get("culture_result")
        if culture_result:
            qs = qs.filter(culture_result=culture_result)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class IsolatedOrganismViewSet(MicrobiologyPermissionsMixin, viewsets.ModelViewSet):
    serializer_class = IsolatedOrganismSerializer

    def get_queryset(self):
        qs = IsolatedOrganism.objects.select_related("result").prefetch_related("antibiogram")
        result = self.request.query_params.get("result")
        if result:
            qs = qs.filter(result_id=result)
        return qs


class AntibiogramEntryViewSet(MicrobiologyPermissionsMixin, viewsets.ModelViewSet):
    serializer_class = AntibiogramEntrySerializer

    def get_queryset(self):
        qs = AntibiogramEntry.objects.select_related("organism")
        # Resistance surveillance filters (antibiotic + interpretation).
        for param, field in (
            ("organism", "organism_id"),
            ("antibiotic", "antibiotic"),
            ("interpretation", "interpretation"),
        ):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{field: value})
        return qs
