"""
H2 — DRF viewsets for doador + triagem sorológica.

Reads require ``hemoterapia.read``, writes require ``hemoterapia.manage`` — the
same per-action gate H1 mounts (reused via ``_HemoterapiaPermissionMixin``).

* :class:`BloodDonorViewSet` — the tenant blood donor cadastro (full CRUD).
* :class:`BloodBagSerologyViewSet` — create routes through
  :func:`apps.emr.services.blood_serology.registrar_sorologia` so the bag's
  quarentena → liberada/descartada transition is atomic; re-testing a
  non-quarentena bag surfaces the service ``ValidationError`` as HTTP 409.
  Read filter ``?bag=``.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.response import Response

from .blood_donor_models import BloodBagSerology, BloodDonor
from .serializers_blood_donor import BloodBagSerologySerializer, BloodDonorSerializer
from .services.blood_serology import registrar_sorologia
from .views import log_audit
from .views_bloodbank import _HemoterapiaPermissionMixin

_BAG_PARAM = OpenApiParameter(
    "bag", OpenApiTypes.UUID, description="Filtra sorologias por bolsa (pk)."
)


@extend_schema_view(
    list=extend_schema(tags=["hemoterapia"], summary="Lista doadores de sangue"),
    create=extend_schema(tags=["hemoterapia"], summary="Cadastra doador de sangue"),
)
class BloodDonorViewSet(_HemoterapiaPermissionMixin, viewsets.ModelViewSet):
    """Doadores de sangue. Read=hemoterapia.read / write=hemoterapia.manage."""

    serializer_class = BloodDonorSerializer
    queryset = BloodDonor.objects.all()

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "blooddonor_create", "BloodDonor", obj.id)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "blooddonor_update", "BloodDonor", obj.id)


@extend_schema_view(
    list=extend_schema(
        tags=["hemoterapia"],
        summary="Lista sorologias de bolsas",
        parameters=[_BAG_PARAM],
    ),
    create=extend_schema(
        tags=["hemoterapia"],
        summary="Registra sorologia (triagem RDC 34) e libera/descarta a bolsa",
        description="Só aceita bolsa em quarentena; re-registrar retorna 409.",
    ),
)
class BloodBagSerologyViewSet(
    _HemoterapiaPermissionMixin,
    viewsets.mixins.CreateModelMixin,
    viewsets.mixins.ListModelMixin,
    viewsets.mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Triagem sorológica de bolsas. Create routes through registrar_sorologia."""

    serializer_class = BloodBagSerologySerializer

    def get_queryset(self):
        qs = BloodBagSerology.objects.select_related("bag", "tested_by")
        bag = self.request.query_params.get("bag")
        if bag:
            qs = qs.filter(bag_id=bag)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bag = serializer.validated_data["bag"]
        resultados = {m: serializer.validated_data[m] for m in BloodBagSerology.PANEL}
        try:
            obj = registrar_sorologia(
                bag,
                resultados,
                by=request.user,
                notes=serializer.validated_data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_409_CONFLICT)
        log_audit(request, "blood_serology_register", "BloodBagSerology", obj.id)
        out = self.get_serializer(obj)
        headers = self.get_success_headers(out.data)
        return Response(out.data, status=status.HTTP_201_CREATED, headers=headers)
