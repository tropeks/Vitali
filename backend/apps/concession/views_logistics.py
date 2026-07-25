"""Gated REST viewsets for the concession logistics chain.

Every viewset is gated ``[IsAuthenticated, ConcessionModule]`` (tier flag
``diagnostic_concession``) and audits state transitions via ``log_audit``.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import AuditLog

from . import services_logistics as svc
from .logistics_models import (
    Dispatch,
    PickList,
    ProofOfDelivery,
    SupplyRequisition,
)
from .permissions import ConcessionModule
from .serializers_logistics import (
    DeliveryInputSerializer,
    DispatchSerializer,
    PickListSerializer,
    ProofOfDeliverySerializer,
    SupplyRequisitionSerializer,
)


def log_audit(request, action_name, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action_name,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=old_data,
        new_data=new_data,
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


def _run(fn, *args, **kwargs):
    """Translate domain ValidationError → DRF 400."""
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise DRFValidationError(getattr(exc, "messages", [str(exc)])) from exc


class SupplyRequisitionViewSet(viewsets.ModelViewSet):
    serializer_class = SupplyRequisitionSerializer
    queryset = SupplyRequisition.objects.all().prefetch_related("items")

    def get_permissions(self):
        return [IsAuthenticated(), ConcessionModule()]

    def perform_create(self, serializer):
        requisition = serializer.save(requested_by=self.request.user)
        log_audit(self.request, "create", "SupplyRequisition", requisition.id)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        requisition = self.get_object()
        _run(svc.submit_requisition, requisition)
        log_audit(request, "submit", "SupplyRequisition", requisition.id)
        return Response(self.get_serializer(requisition).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        requisition = self.get_object()
        _run(svc.approve_requisition, requisition)
        log_audit(request, "approve", "SupplyRequisition", requisition.id)
        return Response(self.get_serializer(requisition).data)


class PickListViewSet(viewsets.ModelViewSet):
    serializer_class = PickListSerializer
    queryset = PickList.objects.all().prefetch_related("items")
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        return [IsAuthenticated(), ConcessionModule()]

    def create(self, request, *args, **kwargs):
        requisition = SupplyRequisition.objects.get(pk=request.data["requisition"])
        pick_list = _run(svc.create_pick_list, requisition)
        log_audit(request, "create", "PickList", pick_list.id)
        return Response(self.get_serializer(pick_list).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def pick(self, request, pk=None):
        from apps.pharmacy.models import StockItem

        from .logistics_models import PickItem

        pick_list = self.get_object()
        pi = PickItem.objects.get(pk=request.data["pick_item"], pick_list=pick_list)
        stock_item = StockItem.objects.get(pk=request.data["source_stock_item"])
        _run(
            svc.pick_item,
            pi,
            source_stock_item=stock_item,
            picked_qty=request.data["picked_qty"],
        )
        log_audit(request, "pick", "PickList", pick_list.id)
        pick_list.refresh_from_db()
        return Response(self.get_serializer(pick_list).data)


class DispatchViewSet(viewsets.ModelViewSet):
    serializer_class = DispatchSerializer
    queryset = Dispatch.objects.all().prefetch_related("items")
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        return [IsAuthenticated(), ConcessionModule()]

    def create(self, request, *args, **kwargs):
        from apps.pharmacy.models import Warehouse

        pick_list = PickList.objects.get(pk=request.data["pick_list"])
        source = Warehouse.objects.get(pk=request.data["source_warehouse"])
        dest_wh = request.data.get("destination_warehouse")
        destination = Warehouse.objects.get(pk=dest_wh) if dest_wh else None
        dispatch = _run(
            svc.create_dispatch,
            pick_list,
            manifest_code=request.data["manifest_code"],
            source_warehouse=source,
            destination_warehouse=destination,
        )
        log_audit(request, "create", "Dispatch", dispatch.id)
        return Response(self.get_serializer(dispatch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        dispatch = self.get_object()
        _run(svc.ship_dispatch, dispatch, performed_by=request.user)
        log_audit(request, "ship", "Dispatch", dispatch.id)
        dispatch.refresh_from_db()
        return Response(self.get_serializer(dispatch).data)

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        dispatch = self.get_object()
        payload = DeliveryInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        proof = _run(
            svc.deliver_dispatch,
            dispatch,
            received_by=data["received_by"],
            signature_ref=data.get("signature_ref", ""),
            geo_lat=data.get("geo_lat"),
            geo_lng=data.get("geo_lng"),
            delivered_at=data.get("delivered_at"),
            captured_by=request.user,
            discrepancies=data.get("discrepancies", []),
        )
        log_audit(request, "deliver", "Dispatch", dispatch.id)
        return Response(ProofOfDeliverySerializer(proof).data, status=status.HTTP_201_CREATED)


class ProofOfDeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProofOfDeliverySerializer
    queryset = ProofOfDelivery.objects.all()

    def get_permissions(self):
        return [IsAuthenticated(), ConcessionModule()]
