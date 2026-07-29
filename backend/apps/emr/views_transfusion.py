"""
H3 — DRF viewsets for the requisição transfusional surface.

Permission split (mirrors the H1 hemoterapia gate):
* create a :class:`TransfusionRequest` → ``hemoterapia.request`` (o médico solicita)
* read (list/retrieve) → ``hemoterapia.read``
* the agência actions ``reservar`` / ``liberar`` / ``cancelar`` → ``hemoterapia.manage``

Reservation/liberation/cancellation are delegated to
:mod:`apps.emr.services.transfusion` (atomic + select_for_update); a service
``ValidationError`` surfaces as HTTP 409 (incompatible/unavailable bag or illegal
transition), never a 400/500.

:class:`CrossMatchViewSet` is read-only (``hemoterapia.read``), filterable by
``?request=``.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .serializers_transfusion import CrossMatchSerializer, TransfusionRequestSerializer
from .services import transfusion as transfusion_service
from .views import log_audit

_REQUEST_PARAM = OpenApiParameter(
    "request", OpenApiTypes.STR, description="Filtra provas de compatibilidade por requisição (pk)."
)
_STATUS_PARAM = OpenApiParameter(
    "status", OpenApiTypes.STR, description="Filtra requisições por situação."
)
_PATIENT_PARAM = OpenApiParameter(
    "patient", OpenApiTypes.STR, description="Filtra requisições por paciente (pk)."
)


class _TransfusionRequestPermissionMixin:
    """create=``hemoterapia.request`` / read=``hemoterapia.read`` / manage actions=``hemoterapia.manage``."""

    _MANAGE_ACTIONS = {"reservar", "liberar", "cancelar"}

    def get_permissions(self):
        if self.action == "create":
            permission = "hemoterapia.request"
        elif self.action in self._MANAGE_ACTIONS:
            permission = "hemoterapia.manage"
        else:  # list, retrieve
            permission = "hemoterapia.read"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista requisições transfusionais",
        parameters=[_STATUS_PARAM, _PATIENT_PARAM],
    ),
    create=extend_schema(tags=["hemoterapia"], summary="Cria requisição transfusional"),
)
class TransfusionRequestViewSet(_TransfusionRequestPermissionMixin, viewsets.ModelViewSet):
    """Requisições transfusionais. create=hemoterapia.request / read=hemoterapia.read /
    reservar+liberar+cancelar=hemoterapia.manage."""

    serializer_class = TransfusionRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        from .models import TransfusionRequest

        qs = TransfusionRequest.objects.select_related(
            "patient", "component", "requester", "created_by"
        ).prefetch_related("crossmatches")
        params = self.request.query_params
        status_param = params.get("status")
        patient = params.get("patient")
        if status_param:
            qs = qs.filter(status=status_param)
        if patient:
            qs = qs.filter(patient_id=patient)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_audit(self.request, "transfusion_request_create", "TransfusionRequest", obj.id)

    def _load_bag(self, bag_id):
        from .models import BloodBag

        try:
            return BloodBag.objects.get(pk=bag_id)
        except (BloodBag.DoesNotExist, ValueError, TypeError):
            return None

    @extend_schema(
        tags=["hemoterapia"],
        summary="Reserva uma bolsa para a requisição (prova de compatibilidade)",
        request={"application/json": {"type": "object", "properties": {"bag": {"type": "string"}}}},
    )
    @action(detail=True, methods=["post"])
    def reservar(self, request, pk=None):
        obj = self.get_object()
        bag_id = request.data.get("bag")
        bag = self._load_bag(bag_id)
        if bag is None:
            return Response({"detail": "Bolsa não encontrada."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            transfusion_service.reservar(obj, bag, actor=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        obj.refresh_from_db()
        log_audit(request, "transfusion_request_reservar", "TransfusionRequest", obj.id)
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)

    @extend_schema(tags=["hemoterapia"], summary="Libera uma requisição reservada", request=None)
    @action(detail=True, methods=["post"])
    def liberar(self, request, pk=None):
        obj = self.get_object()
        try:
            transfusion_service.liberar(obj, actor=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        obj.refresh_from_db()
        log_audit(request, "transfusion_request_liberar", "TransfusionRequest", obj.id)
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["hemoterapia"],
        summary="Cancela a requisição (libera bolsa reservada)",
        request={
            "application/json": {"type": "object", "properties": {"reason": {"type": "string"}}}
        },
    )
    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        obj = self.get_object()
        reason = request.data.get("reason", "")
        try:
            transfusion_service.cancelar(obj, reason=reason, actor=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        obj.refresh_from_db()
        log_audit(request, "transfusion_request_cancelar", "TransfusionRequest", obj.id)
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista provas de compatibilidade",
        parameters=[_REQUEST_PARAM],
    ),
)
class CrossMatchViewSet(viewsets.ReadOnlyModelViewSet):
    """Provas de compatibilidade (read-only). read=hemoterapia.read. Filter ``?request=``."""

    serializer_class = CrossMatchSerializer

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission("hemoterapia.read")]

    def get_queryset(self):
        from .models import CrossMatch

        qs = CrossMatch.objects.select_related("bag", "request", "tested_by")
        request_id = self.request.query_params.get("request")
        if request_id:
            qs = qs.filter(request_id=request_id)
        return qs
