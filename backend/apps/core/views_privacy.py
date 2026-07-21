"""Tenant-scoped LGPD/privacy settings endpoint."""

from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AIDPAStatus, Tenant


class PrivacySettingsSerializer(serializers.Serializer):
    dpo_name = serializers.CharField(max_length=255, allow_blank=True)
    dpo_email = serializers.EmailField(allow_blank=True)
    dpa_signed = serializers.BooleanField()


def _response_data(tenant: Tenant) -> dict:
    return {
        "dpo_name": tenant.dpo_name,
        "dpo_email": tenant.dpo_email,
        "dpa_signed": AIDPAStatus.objects.filter(
            tenant=tenant, dpa_signed_date__isnull=False
        ).exists(),
    }


class PrivacySettingsView(APIView):
    """Read and update privacy settings for the tenant resolved from the host."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_response_data(request.tenant))

    def post(self, request):
        if not IsAdminUser().has_permission(request, self):
            return Response(
                {
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "Apenas administradores podem alterar estas configurações.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PrivacySettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = request.tenant
        requested_signed = serializer.validated_data["dpa_signed"]
        currently_signed = AIDPAStatus.objects.filter(
            tenant=tenant, dpa_signed_date__isnull=False
        ).exists()
        if not requested_signed and currently_signed:
            return Response(
                {
                    "error": {
                        "code": "DPA_SIGNATURE_IMMUTABLE",
                        "message": "Uma assinatura de DPA não pode ser removida por esta tela.",
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        tenant.dpo_name = serializer.validated_data["dpo_name"]
        tenant.dpo_email = serializer.validated_data["dpo_email"]
        tenant.save(update_fields=["dpo_name", "dpo_email", "updated_at"])

        if requested_signed and not currently_signed:
            from .services.dpa import DPASigningService

            DPASigningService(requesting_user=request.user).sign(
                tenant=tenant,
                ip_address=request.META.get("REMOTE_ADDR", "unknown"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        return Response(_response_data(tenant))
