"""
H4 — DRF surface for the checagem beira-leito + administração + reação transfusional.

Permission split:
* run the bedside checagem (``checar``) and record a reaction (``reacao``) →
  ``hemoterapia.transfuse`` (a enfermagem faz a 2ª checagem e administra).
* read (list/retrieve) administrations + reactions → ``hemoterapia.read``.

The ``checar`` endpoint delegates to :mod:`apps.emr.services.transfusion_admin`:
* :class:`~apps.emr.services.transfusion_admin.TransfusionStateError` (request not
  ``liberada``) → HTTP 409.
* :class:`~apps.emr.services.transfusion_admin.ChecagemFailedError` (a certo failed
  without an override) → HTTP 422 with ``{detail, checagem:{...}}``.
* verified or override path → HTTP 201 with the recorded administration.

Administrations + reactions are append-only: read-only viewsets (no PATCH/DELETE),
created only via the actions.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission

from .serializers_transfusion_admin import (
    TransfusionAdministrationSerializer,
    TransfusionReactionSerializer,
)
from .services import transfusion_admin as admin_service
from .views import log_audit

_REQUEST_PARAM = OpenApiParameter(
    "request", OpenApiTypes.STR, description="Filtra administrações por requisição (pk)."
)
_ADMINISTRATION_PARAM = OpenApiParameter(
    "administration", OpenApiTypes.STR, description="Filtra reações por administração (pk)."
)

_CHECAR_REQUEST = {
    "application/json": {
        "type": "object",
        "properties": {
            "bag": {"type": "string"},
            "patient_barcode": {"type": "string"},
            "bag_barcode": {"type": "string"},
            "witness": {"type": "string"},
            "override_reason": {"type": "string"},
        },
        "required": ["bag", "patient_barcode", "bag_barcode"],
    }
}

_REACAO_REQUEST = {
    "application/json": {
        "type": "object",
        "properties": {
            "tipo": {"type": "string"},
            "gravidade": {"type": "string"},
            "descricao": {"type": "string"},
            "conduta": {"type": "string"},
            "notificado_hemovigilancia": {"type": "boolean"},
            "occurred_at": {"type": "string", "format": "date-time"},
        },
        "required": ["tipo", "gravidade", "descricao"],
    }
}


@extend_schema(
    tags=["hemoterapia"],
    summary="Checagem beira-leito + administração transfusional (certos)",
    request=_CHECAR_REQUEST,
    responses={
        201: TransfusionAdministrationSerializer,
        409: OpenApiTypes.OBJECT,
        422: OpenApiTypes.OBJECT,
    },
)
class TransfusionChecarView(APIView):
    """POST /transfusion-requests/{pk}/checar/ — gated ``hemoterapia.transfuse``.

    201 (verified or override), 409 (request not liberada), 422 (certo failed
    without override, with the per-certo ``checagem`` breakdown).
    """

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission("hemoterapia.transfuse")]

    def _load_bag(self, bag_id):
        from .models import BloodBag

        try:
            return BloodBag.objects.get(pk=bag_id)
        except (BloodBag.DoesNotExist, ValueError, TypeError):
            return None

    def _load_user(self, user_id):
        from apps.core.models import User

        try:
            return User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return None

    def post(self, request, pk=None):
        from .models import TransfusionRequest

        try:
            treq = TransfusionRequest.objects.get(pk=pk)
        except (TransfusionRequest.DoesNotExist, ValueError, TypeError):
            return Response(
                {"detail": "Requisição não encontrada."}, status=status.HTTP_404_NOT_FOUND
            )

        bag = self._load_bag(request.data.get("bag"))
        if bag is None:
            return Response({"detail": "Bolsa não encontrada."}, status=status.HTTP_400_BAD_REQUEST)

        witness = None
        witness_id = request.data.get("witness")
        if witness_id:
            witness = self._load_user(witness_id)
            if witness is None:
                return Response(
                    {"detail": "Testemunha não encontrada."}, status=status.HTTP_400_BAD_REQUEST
                )

        try:
            administration = admin_service.checar_e_administrar(
                treq,
                bag,
                patient_barcode=request.data.get("patient_barcode", ""),
                bag_barcode=request.data.get("bag_barcode", ""),
                actor=request.user,
                witness=witness,
                override_reason=request.data.get("override_reason", ""),
            )
        except admin_service.ChecagemFailedError as exc:
            return Response(
                {"detail": exc.messages[0] if exc.messages else str(exc), "checagem": exc.checagem},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except admin_service.TransfusionStateError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        log_audit(request, "transfusion_checar", "TransfusionAdministration", administration.id)
        return Response(
            TransfusionAdministrationSerializer(administration).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista administrações transfusionais",
        parameters=[_REQUEST_PARAM],
    ),
)
class TransfusionAdministrationViewSet(viewsets.ReadOnlyModelViewSet):
    """Administrações transfusionais (append-only, read-only). read=hemoterapia.read.

    ``reacao`` action records a hemovigilância reaction (gated hemoterapia.transfuse).
    """

    serializer_class = TransfusionAdministrationSerializer

    def get_permissions(self):
        if self.action == "reacao":
            return [IsAuthenticated(), HasPermission("hemoterapia.transfuse")]
        return [IsAuthenticated(), HasPermission("hemoterapia.read")]

    def get_queryset(self):
        from .models import TransfusionAdministration

        qs = TransfusionAdministration.objects.select_related(
            "request", "bag", "patient", "administered_by", "witness"
        )
        request_id = self.request.query_params.get("request")
        if request_id:
            qs = qs.filter(request_id=request_id)
        return qs

    @extend_schema(
        tags=["hemoterapia"],
        summary="Registra reação transfusional (hemovigilância)",
        request=_REACAO_REQUEST,
        responses={201: TransfusionReactionSerializer, 400: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["post"])
    def reacao(self, request, pk=None):
        administration = self.get_object()
        required = ("tipo", "gravidade", "descricao")
        missing = [f for f in required if not request.data.get(f)]
        if missing:
            return Response(
                {"detail": f"Campos obrigatórios ausentes: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reaction = admin_service.registrar_reacao(
            administration,
            tipo=request.data["tipo"],
            gravidade=request.data["gravidade"],
            descricao=request.data["descricao"],
            conduta=request.data.get("conduta", ""),
            notificado_hemovigilancia=bool(request.data.get("notificado_hemovigilancia", False)),
            occurred_at=request.data.get("occurred_at") or None,
            actor=request.user,
        )
        log_audit(request, "transfusion_reacao", "TransfusionReaction", reaction.id)
        return Response(
            TransfusionReactionSerializer(reaction).data, status=status.HTTP_201_CREATED
        )


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista reações transfusionais (hemovigilância)",
        parameters=[_ADMINISTRATION_PARAM],
    ),
)
class TransfusionReactionViewSet(viewsets.ReadOnlyModelViewSet):
    """Reações transfusionais (append-only, read-only). read=hemoterapia.read.
    Filter ``?administration=``."""

    serializer_class = TransfusionReactionSerializer

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission("hemoterapia.read")]

    def get_queryset(self):
        from .models import TransfusionReaction

        qs = TransfusionReaction.objects.select_related("administration", "request", "recorded_by")
        administration_id = self.request.query_params.get("administration")
        if administration_id:
            qs = qs.filter(administration_id=administration_id)
        return qs
