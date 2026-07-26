"""Sprint C4 — gated read endpoint for the contract P&L.

``GET /api/v1/concession/contracts/<id>/pnl/?start=&end=&unit=`` returns the
contract P&L (or a single unit's, when ``unit`` is given). Gated on
``[IsAuthenticated, ConcessionModule]`` — a tenant without the
``diagnostic_concession`` tier gets 403. Read-only, so nothing is audited.
"""

import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import AuditLog
from apps.organization.models import Facility

from .contract_models import ConcessionContract
from .permissions import ConcessionModule
from .pnl_models import ExamConsumption, MaterialUnitCost
from .serializers_pnl import (
    ExamConsumptionRecordSerializer,
    ExamConsumptionSerializer,
    MaterialUnitCostSerializer,
    PnlQuerySerializer,
)
from .services_pnl import contract_pnl, record_exam_consumption, unit_pnl


def _json_safe(data):
    if data is None:
        return None
    return json.loads(json.dumps(data, default=str))


def log_audit(request, action_name, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action_name,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=_json_safe(old_data),
        new_data=_json_safe(new_data),
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


def _run(fn, *args, **kwargs):
    """Translate a domain ValidationError → DRF 400."""
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise DRFValidationError(getattr(exc, "messages", [str(exc)])) from exc


@extend_schema_view(
    list=extend_schema(responses=MaterialUnitCostSerializer(many=True)),
    retrieve=extend_schema(responses=MaterialUnitCostSerializer),
    create=extend_schema(request=MaterialUnitCostSerializer, responses=MaterialUnitCostSerializer),
    update=extend_schema(request=MaterialUnitCostSerializer, responses=MaterialUnitCostSerializer),
    partial_update=extend_schema(
        request=MaterialUnitCostSerializer, responses=MaterialUnitCostSerializer
    ),
    destroy=extend_schema(responses={204: None}),
)
class MaterialUnitCostViewSet(viewsets.ModelViewSet):
    """B0-T3 — CRUD for the operator's concession-local material cost basis."""

    queryset = MaterialUnitCost.objects.select_related("material").all()
    serializer_class = MaterialUnitCostSerializer
    permission_classes = [IsAuthenticated, ConcessionModule]

    def perform_create(self, serializer):
        row = serializer.save()
        log_audit(self.request, "create", "MaterialUnitCost", row.pk, new_data=serializer.data)

    def perform_update(self, serializer):
        old = MaterialUnitCostSerializer(serializer.instance).data
        row = serializer.save()
        log_audit(
            self.request,
            "update",
            "MaterialUnitCost",
            row.pk,
            old_data=old,
            new_data=serializer.data,
        )

    def perform_destroy(self, instance):
        log_audit(self.request, "delete", "MaterialUnitCost", instance.pk)
        instance.delete()


@extend_schema_view(
    list=extend_schema(responses=ExamConsumptionSerializer(many=True)),
    retrieve=extend_schema(responses=ExamConsumptionSerializer),
)
class ExamConsumptionViewSet(viewsets.ReadOnlyModelViewSet):
    """B0-T4 — append-only consumption ledger (list/retrieve only) plus a manual
    ``record`` endpoint for non-DICOM exams.

    The model refuses updates/deletes, so no PUT/PATCH/DELETE is exposed.
    """

    queryset = ExamConsumption.objects.select_related("unit", "service").all()
    serializer_class = ExamConsumptionSerializer
    permission_classes = [IsAuthenticated, ConcessionModule]

    def get_queryset(self):
        qs = ExamConsumption.objects.select_related("unit", "service").all()
        unit_id = self.request.query_params.get("unit")
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        service_id = self.request.query_params.get("service")
        if service_id:
            qs = qs.filter(service_id=service_id)
        return qs

    @extend_schema(
        request=ExamConsumptionRecordSerializer,
        responses={201: ExamConsumptionSerializer},
    )
    @action(detail=False, methods=["post"])
    def record(self, request):
        """Record one manual (non-DICOM) exam's consumption, delegating to
        ``services_pnl.record_exam_consumption`` (deducts recipe from stock,
        freezes cost). Idempotent per ``(unit, service, external_ref)``."""
        payload = ExamConsumptionRecordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        consumption = _run(
            record_exam_consumption,
            data["service"],
            data["unit"],
            data["external_ref"],
            warehouse=data.get("warehouse"),
            performed_at=data.get("performed_at"),
            performed_by=request.user,
        )
        out = ExamConsumptionSerializer(consumption).data
        log_audit(request, "record", "ExamConsumption", consumption.pk, new_data=out)
        return Response(out, status=status.HTTP_201_CREATED)


class ContractPnlViewSet(viewsets.GenericViewSet):
    """Exposes only the ``pnl`` detail action on a concession contract."""

    permission_classes = [IsAuthenticated, ConcessionModule]
    queryset = ConcessionContract.objects.all()

    @action(detail=True, methods=["get"], url_path="pnl")
    def pnl(self, request, pk=None):
        contract = self.get_object()
        params = PnlQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        start = params.validated_data.get("start")
        end = params.validated_data.get("end")
        unit_id = params.validated_data.get("unit")
        if unit_id:
            unit = get_object_or_404(Facility, pk=unit_id)
            data = unit_pnl(contract, unit, start, end)
        else:
            data = contract_pnl(contract, start, end)
        return Response(data)
