from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .models import ApprovalRequest
from .serializers import ApprovalDecisionSerializer, ApprovalRequestSerializer
from .services import ApprovalService


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
