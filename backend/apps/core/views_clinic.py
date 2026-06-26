"""
Issue #116: Clinic identity settings consumed by the onboarding wizard (Step 1).

GET   /api/v1/settings/clinic/  — return the current tenant's clinic identity.
PATCH /api/v1/settings/clinic/  — admin-only; update CNPJ, razão social,
                                  endereço and the DPO (encarregado) contact so a
                                  non-technical admin can finish onboarding without
                                  engineering support.

The Tenant row lives in the PUBLIC schema (apps.core is SHARED), but ``request.tenant``
is the resolved Tenant instance — writing to it from inside a tenant request is the
same cross-schema pattern already used by the DPA signing flow (views_dpa.py).
"""

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Tenant
from .permissions import HasPermission

# Onboarding/clinic identity is an admin-tier capability. ``users.write`` is granted
# only to the default ``admin`` role, so it cleanly restricts this to clinic admins
# (platform superusers bypass via HasPermission) without a new permission key that
# existing tenants' seeded roles would lack.
_CLINIC_ADMIN = HasPermission("users.write")


class ClinicProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "name",
            "cnpj",
            "razao_social",
            "address",
            "dpo_name",
            "dpo_email",
            "dpo_phone",
        ]

    def validate_cnpj(self, value):
        # Normalise blank to NULL so the unique constraint never trips on "".
        return value or None


class ClinicProfileView(APIView):
    """GET/PATCH the clinic identity for the authenticated tenant."""

    permission_classes = [IsAuthenticated, _CLINIC_ADMIN]

    @staticmethod
    def _tenant(request):
        return getattr(request, "tenant", None)

    def get(self, request):
        tenant = self._tenant(request)
        if tenant is None:
            return Response(
                {"error": {"code": "NO_TENANT", "message": "Tenant não resolvido."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ClinicProfileSerializer(tenant).data)

    def patch(self, request):
        tenant = self._tenant(request)
        if tenant is None:
            return Response(
                {"error": {"code": "NO_TENANT", "message": "Tenant não resolvido."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ClinicProfileSerializer(tenant, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "details": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
