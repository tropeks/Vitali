"""
H1 — DRF viewsets for the Banco de Sangue/Hemoterapia surface.

Permission split (mirrors the sigtap/beds/surgery pattern): reads require
``hemoterapia.read``, all writes require ``hemoterapia.manage`` — gated per-action
via ``get_permissions``. No agência-transfusional role exists, so ``manage`` is
admin-only (see apps.core.permissions).

* :class:`BloodComponentViewSet` — the SHARED governed hemocomponente catalog
  (``core.BloodComponentCatalog``). Filter ``?q=`` (accent/case-insensitive) and
  ``?context=``. The catalog lives in the public schema but authorization is
  per-tenant-role, so it mounts on the tenant-facing API.
* :class:`BloodBagViewSet` — the tenant blood bag stock. Filter
  ``?component=&abo=&rh_factor=&serology_status=&stock_status=&available=true``.
  ``created_by`` is stamped server-side on create.
"""

from __future__ import annotations

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.blood_catalog_models import BloodComponentCatalog
from apps.core.permissions import HasPermission
from apps.core.terminology_base import normalize_text

from .serializers_bloodbank import BloodBagSerializer, BloodComponentSerializer
from .views import log_audit

_Q_PARAM = OpenApiParameter(
    "q", OpenApiTypes.STR, description="Busca acento/maiúsculas-insensível por display/código."
)
_CONTEXT_PARAM = OpenApiParameter(
    "context", OpenApiTypes.STR, description="Filtra hemocomponentes por contexto/grupo."
)
_COMPONENT_PARAM = OpenApiParameter(
    "component", OpenApiTypes.STR, description="Filtra bolsas por hemocomponente (pk)."
)
_ABO_PARAM = OpenApiParameter("abo", OpenApiTypes.STR, description="Filtra por grupo ABO.")
_RH_PARAM = OpenApiParameter("rh_factor", OpenApiTypes.STR, description="Filtra por fator Rh.")
_SEROLOGY_PARAM = OpenApiParameter(
    "serology_status", OpenApiTypes.STR, description="Filtra por situação sorológica."
)
_STOCK_PARAM = OpenApiParameter(
    "stock_status", OpenApiTypes.STR, description="Filtra por situação de estoque."
)
_AVAILABLE_PARAM = OpenApiParameter(
    "available",
    OpenApiTypes.BOOL,
    description="available=true → só bolsas disponíveis (sorologia liberada, "
    "estoque disponível e não vencidas).",
)


class _HemoterapiaPermissionMixin:
    """Read=``hemoterapia.read`` / write=``hemoterapia.manage`` per-action gate."""

    def get_permissions(self):
        read_actions = {"list", "retrieve"}
        permission = "hemoterapia.read" if self.action in read_actions else "hemoterapia.manage"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista hemocomponentes (catálogo)",
        parameters=[_Q_PARAM, _CONTEXT_PARAM],
    ),
)
class BloodComponentViewSet(_HemoterapiaPermissionMixin, viewsets.ModelViewSet):
    """Hemocomponentes (catálogo governado). Read=hemoterapia.read / write=hemoterapia.manage."""

    serializer_class = BloodComponentSerializer

    def get_queryset(self):
        qs = BloodComponentCatalog.objects.all().order_by("code")
        context = self.request.query_params.get("context")
        if context:
            qs = qs.filter(context=context)
        q = self.request.query_params.get("q")
        if q:
            from django.db.models import Q

            norm = normalize_text(q)
            match = Q(code__icontains=q)
            if norm:
                match |= Q(normalized_display__contains=norm)
            qs = qs.filter(match)
        return qs


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista bolsas de sangue (estoque)",
        parameters=[
            _COMPONENT_PARAM,
            _ABO_PARAM,
            _RH_PARAM,
            _SEROLOGY_PARAM,
            _STOCK_PARAM,
            _AVAILABLE_PARAM,
        ],
    ),
)
class BloodBagViewSet(_HemoterapiaPermissionMixin, viewsets.ModelViewSet):
    """Bolsas de sangue (estoque). Read=hemoterapia.read / write=hemoterapia.manage."""

    serializer_class = BloodBagSerializer

    def get_queryset(self):
        from .models import BloodBag

        qs = BloodBag.objects.select_related("component", "created_by")
        params = self.request.query_params
        component = params.get("component")
        abo = params.get("abo")
        rh_factor = params.get("rh_factor")
        serology_status = params.get("serology_status")
        stock_status = params.get("stock_status")
        if component:
            qs = qs.filter(component_id=component)
        if abo:
            qs = qs.filter(abo=abo)
        if rh_factor:
            qs = qs.filter(rh_factor=rh_factor)
        if serology_status:
            qs = qs.filter(serology_status=serology_status)
        if stock_status:
            qs = qs.filter(stock_status=stock_status)
        if params.get("available", "").lower() in ("1", "true", "yes"):
            today = timezone.now().date()
            qs = qs.filter(
                serology_status=BloodBag.SerologyStatus.LIBERADA,
                stock_status=BloodBag.StockStatus.DISPONIVEL,
                expiry_date__gte=today,
            )
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_audit(self.request, "bloodbag_create", "BloodBag", obj.id)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "bloodbag_update", "BloodBag", obj.id)
