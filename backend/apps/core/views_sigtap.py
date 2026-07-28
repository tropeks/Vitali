"""
S1 — DRF viewset for the SIGTAP catalog (SHARED / public schema).

Governed CRUD over ``core.SIGTAPProcedure``. Permission split mirrors the
Manchester/beds/surgery pattern: reads require ``sus.read``, all writes require
``sus.write`` (gated per-action via ``get_permissions``). The catalog lives in
the public schema but authorization is per-tenant-role, so these routes mount on
the tenant-facing API (``apps.core.urls``).

Filtering:
  * ``?q=``            — accent/case-insensitive display/code search.
  * ``?instrumento=``  — filter by instrumento de registro (bpa_c/bpa_i/apac/aih/outros).
  * ``?complexidade=`` — filter by complexidade (atencao_basica/media/alta/nao_se_aplica).
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasPermission
from apps.core.serializers_sigtap import SIGTAPProcedureSerializer
from apps.core.sigtap_catalog_models import SIGTAPProcedure
from apps.core.terminology_base import normalize_text

_Q_PARAM = OpenApiParameter(
    "q", OpenApiTypes.STR, description="Busca acento/maiúsculas-insensível por display/código."
)
_INSTRUMENTO_PARAM = OpenApiParameter(
    "instrumento",
    OpenApiTypes.STR,
    description="Filtra por instrumento de registro (bpa_c/bpa_i/apac/aih/outros).",
)
_COMPLEXIDADE_PARAM = OpenApiParameter(
    "complexidade",
    OpenApiTypes.STR,
    description="Filtra por complexidade (atencao_basica/media/alta/nao_se_aplica).",
)


class _SusPermissionMixin:
    """Read=``sus.read`` / write=``sus.write`` per-action gate."""

    def get_permissions(self):
        read_actions = {"list", "retrieve"}
        permission = "sus.read" if self.action in read_actions else "sus.write"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(
        tags=["sigtap"],
        summary="Lista procedimentos SIGTAP",
        parameters=[_Q_PARAM, _INSTRUMENTO_PARAM, _COMPLEXIDADE_PARAM],
    ),
)
class SIGTAPProcedureViewSet(_SusPermissionMixin, viewsets.ModelViewSet):
    """Procedimentos SIGTAP (SUS). Read=sus.read / write=sus.write."""

    serializer_class = SIGTAPProcedureSerializer

    def get_queryset(self):
        qs = SIGTAPProcedure.objects.all().order_by("code")
        instrumento = self.request.query_params.get("instrumento")
        if instrumento:
            qs = qs.filter(instrumento_registro=instrumento)
        complexidade = self.request.query_params.get("complexidade")
        if complexidade:
            qs = qs.filter(complexidade=complexidade)
        q = self.request.query_params.get("q")
        if q:
            from django.db.models import Q

            norm = normalize_text(q)
            match = Q(code__icontains=q)
            if norm:
                match |= Q(normalized_display__contains=norm)
            qs = qs.filter(match)
        return qs
