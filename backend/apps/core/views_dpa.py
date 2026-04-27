"""
S-070 / S-081: DPA Signing UI endpoints.

GET  /api/v1/settings/dpa/  — return current DPA status for tenant
POST /api/v1/settings/dpa/sign/ — admin-only, sign the DPA + cascade AI flags

S-081: DPASignView.post() is now a thin wrapper around DPASigningService.sign(),
which atomically enables per-tenant AI FeatureFlag rows and queues an admin
notification email via transaction.on_commit (fail-open, decision 1B).
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AIDPAStatus

logger = logging.getLogger(__name__)

DPA_SIGN_PERMISSION = "ai.manage"


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _user_can_sign_dpa(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = getattr(user, "role", None)
    if not role:
        return False
    return DPA_SIGN_PERMISSION in (role.permissions or [])


def _dpa_response(dpa_status, user) -> dict:
    can_sign = _user_can_sign_dpa(user)
    if dpa_status is None:
        return {
            "is_signed": False,
            "signed_at": None,
            "signed_by_name": None,
            "ai_scribe_enabled": getattr(settings, "FEATURE_AI_SCRIBE", False),
            "current_user_can_sign": can_sign,
        }
    return {
        "is_signed": dpa_status.is_signed,
        "signed_at": dpa_status.dpa_signed_date.isoformat() if dpa_status.dpa_signed_date else None,
        "signed_by_name": dpa_status.signed_by_user.full_name
        if dpa_status.signed_by_user
        else None,
        "ai_scribe_enabled": getattr(settings, "FEATURE_AI_SCRIBE", False),
        "current_user_can_sign": can_sign,
    }


class DPAStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            dpa_status = AIDPAStatus.objects.get(tenant=request.tenant)
        except AIDPAStatus.DoesNotExist:
            return Response(_dpa_response(None, request.user))
        return Response(_dpa_response(dpa_status, request.user))


class DPASignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _user_can_sign_dpa(request.user):
            return Response(
                {
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "Apenas administradores podem assinar o DPA.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        from apps.core.services.dpa import DPASigningService

        service = DPASigningService(requesting_user=request.user)
        result = service.sign(
            tenant=request.tenant,
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(_dpa_response(result["dpa_status"], request.user))
