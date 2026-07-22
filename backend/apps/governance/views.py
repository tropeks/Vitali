from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission

from .models import ApprovalRequest, DomainEventOutbox, IntegrationInbox
from .serializers import (
    ApprovalDecisionSerializer,
    ApprovalRequestSerializer,
    DomainEventOutboxSerializer,
    IntegrationInboxSerializer,
)
from .services import ApprovalService, InboxService, OutboxService


class ApprovalRequestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ApprovalRequest.objects.prefetch_related("steps").select_related("requested_by")
    serializer_class = ApprovalRequestSerializer

    def get_permissions(self):
        if self.action in {"approve", "reject"}:
            permission = "workflow.approve"
        elif self.action == "cancel":
            permission = "workflow.request"
        else:
            permission = "workflow.read"
        return [IsAuthenticated(), HasPermission(permission)]

    def _decide(self, request, *, approve: bool):
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            approval = ApprovalService.decide(
                approval_id=self.kwargs["pk"],
                actor=request.user,
                approve=approve,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(ApprovalRequestSerializer(approval).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        return self._decide(request, approve=True)

    @action(detail=True, methods=("post",))
    def reject(self, request, pk=None):
        return self._decide(request, approve=False)

    @action(detail=True, methods=("post",))
    def cancel(self, request, pk=None):
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            approval = ApprovalService.cancel(
                approval_id=self.kwargs["pk"],
                actor=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(ApprovalRequestSerializer(approval).data, status=status.HTTP_200_OK)


class _IntegrationOperationsViewSet(viewsets.ReadOnlyModelViewSet):
    filterset_fields = ("status",)
    search_fields = ("idempotency_key", "correlation_id")

    def get_permissions(self):
        permission = (
            "integrations.replay" if self.action == "replay" else "integrations.operations.read"
        )
        return [IsAuthenticated(), HasPermission(permission)]

    @action(detail=True, methods=("post",))
    def replay(self, request, pk=None):
        try:
            instance = self.get_object()
            instance = self.replay_service(instance)
            AuditLog.objects.create(
                user=request.user,
                action="integration_replay",
                resource_type=instance._meta.model_name,
                resource_id=str(instance.pk),
                new_data={"status": instance.status},
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(instance).data)


class IntegrationInboxViewSet(_IntegrationOperationsViewSet):
    queryset = IntegrationInbox.objects.all()
    serializer_class = IntegrationInboxSerializer
    replay_service = staticmethod(InboxService.replay)
    filterset_fields = ("status", "source", "message_type")
    search_fields = ("idempotency_key", "correlation_id")


class DomainEventOutboxViewSet(_IntegrationOperationsViewSet):
    queryset = DomainEventOutbox.objects.all()
    serializer_class = DomainEventOutboxSerializer
    replay_service = staticmethod(OutboxService.replay)
    filterset_fields = ("status", "event_type", "aggregate_type")
    search_fields = ("idempotency_key", "aggregate_id")
