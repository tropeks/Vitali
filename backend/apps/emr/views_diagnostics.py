from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .models import CriticalLabResult, LabInstrument, LabOrderItem, LabSpecimen
from .serializers_diagnostics import (
    CriticalLabResultSerializer,
    LabInstrumentSerializer,
    LabSpecimenSerializer,
)
from .services.diagnostics import (
    acknowledge_critical_result,
    open_critical_result,
    transition_specimen,
)


class DiagnosticsPermissionsMixin:
    def get_permissions(self):
        permission = "emr.read" if self.action in {"list", "retrieve"} else "emr.write"
        return [IsAuthenticated(), HasPermission(permission)]


class LabInstrumentViewSet(DiagnosticsPermissionsMixin, viewsets.ModelViewSet):
    queryset = LabInstrument.objects.all()
    serializer_class = LabInstrumentSerializer


class LabSpecimenViewSet(DiagnosticsPermissionsMixin, viewsets.ModelViewSet):
    queryset = LabSpecimen.objects.select_related("order", "collected_by").prefetch_related(
        "events"
    )
    serializer_class = LabSpecimenSerializer

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        instrument = None
        if request.data.get("instrument"):
            instrument = LabInstrument.objects.filter(
                pk=request.data["instrument"], is_active=True
            ).first()
            if instrument is None:
                return Response({"instrument": "Equipamento inválido."}, status=400)
        specimen = transition_specimen(
            self.get_object(),
            request.data.get("status", ""),
            request.user,
            location=request.data.get("location", ""),
            reason=request.data.get("reason", ""),
            instrument=instrument,
        )
        return Response(self.get_serializer(specimen).data)


class CriticalLabResultViewSet(DiagnosticsPermissionsMixin, viewsets.ReadOnlyModelViewSet):
    queryset = CriticalLabResult.objects.select_related(
        "order_item", "detected_by", "acknowledged_by"
    )
    serializer_class = CriticalLabResultSerializer

    @action(detail=False, methods=["post"])
    def detect(self, request):
        item = LabOrderItem.objects.filter(pk=request.data.get("order_item")).first()
        if item is None:
            return Response({"order_item": "Item não encontrado."}, status=404)
        critical = open_critical_result(item, request.user)
        return Response(self.get_serializer(critical).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        critical = acknowledge_critical_result(
            self.get_object(), request.user, request.data.get("note", "")
        )
        return Response(self.get_serializer(critical).data)
