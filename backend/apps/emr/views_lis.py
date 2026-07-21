import hmac
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission

from .models import LabIntegrationMessage, LabOrder
from .serializers_lis import LabIntegrationMessageSerializer
from .services.lis import apply_message, normalize_payload, payload_digest, render_orm


class LISInboundView(APIView):
    """Authenticated transport-neutral inbox; clinical application is a separate operator step."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        configured_secret = getattr(settings, "LIS_INBOUND_SECRET", "")
        supplied_secret = request.headers.get("X-Vitali-LIS-Secret", "")
        if not configured_secret or not hmac.compare_digest(configured_secret, supplied_secret):
            return Response({"detail": "Credencial LIS inválida."}, status=401)
        source = request.headers.get("X-Vitali-LIS-Source", "").strip()
        if not source or len(source) > 80:
            return Response({"source": "Identificador de origem inválido."}, status=400)
        format_name = request.data.get("format", LabIntegrationMessage.Format.CANONICAL)
        payload = request.data.get("payload")
        try:
            canonical, raw = normalize_payload(format_name, payload)
        except ValidationError as exc:
            AuditLog.objects.create(
                user=None,
                action="lis_message_reject",
                resource_type="LISInbound",
                resource_id="",
                new_data={"source": source, "reason": "invalid_payload"},
                ip_address=request.META.get("REMOTE_ADDR") or None,
            )
            raise exc
        digest = payload_digest(raw)
        values = {
            "format": format_name,
            "payload_hash": digest,
            "raw_payload": raw,
            "canonical_payload": canonical,
            "status": LabIntegrationMessage.Status.PENDING,
        }
        try:
            with transaction.atomic():
                message, created = LabIntegrationMessage.objects.get_or_create(
                    source=source,
                    message_id=str(canonical["message_id"])[:120],
                    direction=LabIntegrationMessage.Direction.INBOUND,
                    defaults=values,
                )
        except IntegrityError:
            message = LabIntegrationMessage.objects.get(
                source=source,
                message_id=str(canonical["message_id"])[:120],
                direction=LabIntegrationMessage.Direction.INBOUND,
            )
            created = False
        if not created and message.payload_hash != digest:
            return Response(
                {"detail": "message_id já recebido com conteúdo diferente."}, status=409
            )
        if created:
            AuditLog.objects.create(
                user=None,
                action="lis_message_receive",
                resource_type="LabIntegrationMessage",
                resource_id=str(message.id),
                new_data={"source": source, "message_id": message.message_id},
                ip_address=request.META.get("REMOTE_ADDR") or None,
            )
        return Response(
            {"id": message.id, "status": message.status, "duplicate": not created},
            status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
        )


class LabIntegrationMessageViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LabIntegrationMessageSerializer
    permission_classes = [IsAuthenticated, HasPermission("emr.read")]  # type: ignore[list-item]

    def get_queryset(self):
        queryset = LabIntegrationMessage.objects.select_related("lab_order", "applied_by")
        message_status = self.request.query_params.get("status")
        if message_status:
            queryset = queryset.filter(status=message_status)
        return queryset

    def get_permissions(self):
        if self.action == "apply":
            return [IsAuthenticated(), HasPermission("emr.write")]
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        message = self.get_object()
        try:
            message = apply_message(message, request.user, request.META.get("REMOTE_ADDR", ""))
        except ValidationError as exc:
            return Response(exc.detail, status=409)
        return Response(self.get_serializer(message).data)


class LabOrderORMView(APIView):
    permission_classes = [IsAuthenticated, HasPermission("emr.read")]  # type: ignore[list-item]

    def get(self, request, order_id):
        try:
            order = (
                LabOrder.objects.select_related("patient")
                .prefetch_related("items__test")
                .get(pk=order_id)
            )
        except LabOrder.DoesNotExist:
            return Response({"detail": "Pedido não encontrado."}, status=404)
        message_id = str(uuid.uuid4())
        raw = render_orm(order, message_id)
        LabIntegrationMessage.objects.create(
            source="vitali",
            message_id=message_id,
            direction=LabIntegrationMessage.Direction.OUTBOUND,
            format=LabIntegrationMessage.Format.HL7_V2,
            payload_hash=payload_digest(raw),
            raw_payload=raw,
            canonical_payload={"order_id": str(order.id)},
            status=LabIntegrationMessage.Status.APPLIED,
            lab_order=order,
            applied_by=request.user,
            applied_at=order.requested_at,
        )
        AuditLog.objects.create(
            user=request.user,
            action="lis_orm_export",
            resource_type="LabOrder",
            resource_id=str(order.id),
            new_data={"message_id": message_id},
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
        return Response(
            {"message_id": message_id, "format": "hl7_v2", "payload": raw},
            content_type="application/json",
        )
