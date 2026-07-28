"""
E1 — DRF viewsets for the Manchester triage catalog (SHARED / public schema).

Read-only-ish governed CRUD over ``core.ManchesterFlowchart`` and
``core.ManchesterDiscriminator``. Permission split mirrors the surgery/beds
pattern: reads require ``emergency.read``, all writes require ``emergency.manage``
(gated per-action via ``get_permissions``). The catalog lives in the public
schema but authorization is per-tenant-role, so these routes mount on the
tenant-facing API (``apps.core.urls``).

Filtering:
  * flowcharts  — ``?system=`` and ``?q=`` (accent/case-insensitive display/code).
  * discriminators — ``?flowchart=`` (UUID/pk of the parent fluxograma).
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.manchester_catalog_models import (
    ManchesterDiscriminator,
    ManchesterFlowchart,
)
from apps.core.permissions import HasPermission
from apps.core.serializers_manchester import (
    ManchesterDiscriminatorSerializer,
    ManchesterFlowchartSerializer,
)
from apps.core.terminology_base import normalize_text

_SYSTEM_PARAM = OpenApiParameter(
    "system", OpenApiTypes.STR, description="Filtra por sistema de terminologia."
)
_Q_PARAM = OpenApiParameter(
    "q", OpenApiTypes.STR, description="Busca acento/maiúsculas-insensível por display/código."
)
_FLOWCHART_PARAM = OpenApiParameter(
    "flowchart", OpenApiTypes.STR, description="Filtra discriminadores por fluxograma (pk)."
)


class _EmergencyPermissionMixin:
    """Read=``emergency.read`` / write=``emergency.manage`` per-action gate."""

    def get_permissions(self):
        read_actions = {"list", "retrieve"}
        permission = "emergency.read" if self.action in read_actions else "emergency.manage"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(
        tags=["manchester"],
        summary="Lista fluxogramas Manchester",
        parameters=[_SYSTEM_PARAM, _Q_PARAM],
    ),
)
class ManchesterFlowchartViewSet(_EmergencyPermissionMixin, viewsets.ModelViewSet):
    """Fluxogramas de apresentação Manchester. Read=emergency.read / write=emergency.manage."""

    serializer_class = ManchesterFlowchartSerializer

    def get_queryset(self):
        qs = ManchesterFlowchart.objects.all().order_by("code")
        system = self.request.query_params.get("system")
        if system:
            qs = qs.filter(system=system)
        q = self.request.query_params.get("q")
        if q:
            norm = normalize_text(q)
            from django.db.models import Q

            match = Q(code__icontains=q)
            if norm:
                match |= Q(normalized_display__contains=norm)
            qs = qs.filter(match)
        return qs


@extend_schema_view(
    list=extend_schema(
        tags=["manchester"],
        summary="Lista discriminadores Manchester",
        parameters=[_FLOWCHART_PARAM],
    ),
)
class ManchesterDiscriminatorViewSet(_EmergencyPermissionMixin, viewsets.ModelViewSet):
    """Discriminadores Manchester. Read=emergency.read / write=emergency.manage."""

    serializer_class = ManchesterDiscriminatorSerializer

    def get_queryset(self):
        qs = ManchesterDiscriminator.objects.select_related("flowchart").order_by(
            "flowchart", "code"
        )
        flowchart = self.request.query_params.get("flowchart")
        if flowchart:
            qs = qs.filter(flowchart_id=flowchart)
        return qs
