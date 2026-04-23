"""
S-070: DPA Signing UI endpoints.

GET  /api/v1/settings/dpa/  — return current DPA status for tenant
POST /api/v1/settings/dpa/sign/ — admin-only, sign the DPA
"""

import logging
from datetime import date

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AIDPAStatus, AuditLog

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

        dpa_status, _ = AIDPAStatus.objects.get_or_create(tenant=request.tenant)

        if dpa_status.is_signed:
            return Response(_dpa_response(dpa_status, request.user))

        dpa_status.dpa_signed_date = date.today()
        dpa_status.signed_by_user = request.user
        dpa_status.save(update_fields=["dpa_signed_date", "signed_by_user"])

        try:
            AuditLog.objects.create(
                user=request.user,
                action="dpa_sign",
                resource_type="ai_dpa_status",
                resource_id=str(dpa_status.pk),
                new_data={
                    "signed_at": date.today().isoformat(),
                    "signed_by_id": str(request.user.pk),
                },
                ip_address=_get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
        except Exception as exc:
            logger.warning("DPASignView: failed to write audit log: %s", exc)

        return Response(_dpa_response(dpa_status, request.user))
