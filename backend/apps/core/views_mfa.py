"""
DRF views for S-062 MFA endpoints.

Endpoints:
  POST /auth/mfa/setup/     — generate secret + QR code
  POST /auth/mfa/verify/    — confirm TOTP, activate device, return backup codes
  POST /auth/mfa/login/     — second-factor login; re-issue JWT with mfa_verified claim
  POST /auth/mfa/disable/   — platform admin: disable MFA for a user

JWT with mfa_verified claim:
  Uses simplejwt RefreshToken and injects a custom 'mfa_verified' claim.
"""

import logging
import uuid

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .mfa import (
    activate_device,
    check_backup_code,
    generate_qr_image_base64,
    generate_qr_uri,
    get_or_create_device,
    verify_totp_code,
)
from .throttles_mfa import MFAVerifyThrottle

User = get_user_model()
logger = logging.getLogger(__name__)


def _issue_mfa_jwt(user) -> dict:
    """
    Issue a JWT pair with mfa_verified=True claim.
    Returns {'access': '...', 'refresh': '...'}.
    """
    refresh = RefreshToken.for_user(user)
    refresh["mfa_verified"] = True
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


class MFAStatusView(APIView):
    """
    GET /auth/mfa/status/

    Returns whether MFA is active for the authenticated user.
    Response: {is_active: bool}
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            device = request.user.totp_device
            is_active = bool(device.is_active)
        except Exception:
            is_active = False
        return Response({"is_active": is_active}, status=status.HTTP_200_OK)


class MFASetupView(APIView):
    """
    POST /auth/mfa/setup/

    Generate a new TOTP secret and QR code for the authenticated user.
    Creates (or resets) an inactive TOTPDevice.
    Returns: {secret, qr_uri, qr_image_base64}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        device = get_or_create_device(request.user)
        secret = device.encrypted_secret
        uri = generate_qr_uri(request.user.email, secret)
        qr_b64 = generate_qr_image_base64(uri)

        return Response(
            {
                "secret": secret,
                "qr_uri": uri,
                "qr_image_base64": qr_b64,
            },
            status=status.HTTP_200_OK,
        )


class MFAVerifyView(APIView):
    """
    POST /auth/mfa/verify/

    Confirm a TOTP code to activate the device.
    Rate-limited to 3 attempts per 5 minutes.
    On success: activates device, returns {backup_codes: [...]}.
    On failure: 400 {error: "Código inválido"}.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [MFAVerifyThrottle]

    def post(self, request):
        code = request.data.get("code", "").strip()
        if not code:
            return Response(
                {"error": "Código TOTP é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            device = request.user.totp_device
        except Exception:
            return Response(
                {"error": "Dispositivo MFA não configurado. Chame /auth/mfa/setup/ primeiro."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if device.is_active:
            return Response(
                {"error": "MFA já está ativo para este usuário."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        success, backup_codes = activate_device(device, code)
        if not success:
            return Response(
                {"error": "Código inválido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("MFA activated for user %s", request.user.id)
        return Response(
            {"backup_codes": backup_codes},
            status=status.HTTP_200_OK,
        )


class MFALoginView(APIView):
    """
    POST /auth/mfa/login/

    Second-factor login. The caller must already have a valid JWT (partial auth —
    credential-based) but WITHOUT the mfa_verified claim.

    Body:
      {code: "123456"}      — TOTP code
      {backup_code: "XXXX-XXXX"} — backup code (consumed on use)

    On success: re-issues JWT pair with mfa_verified=True.
    On failure: 400 {error: "Código inválido"}.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [MFAVerifyThrottle]

    def post(self, request):
        # Reject if mfa_verified is already True (prevent double-submit)
        from .mfa import is_mfa_verified

        if is_mfa_verified(request):
            return Response(
                {"error": "MFA já verificado nesta sessão."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            device = request.user.totp_device
        except Exception:
            return Response(
                {"error": "MFA não configurado para este usuário."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not device.is_active:
            return Response(
                {"error": "Dispositivo MFA não ativado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Try TOTP code first, then backup code
        totp_code = request.data.get("code", "").strip()
        backup_code = request.data.get("backup_code", "").strip()

        verified = False
        if totp_code:
            secret = device.encrypted_secret
            verified = verify_totp_code(secret, totp_code)
        elif backup_code:
            verified = check_backup_code(device, backup_code)

        if not verified:
            return Response(
                {"error": "Código inválido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Re-issue JWT with mfa_verified=True
        tokens = _issue_mfa_jwt(request.user)
        logger.info("MFA login successful for user %s", request.user.id)
        return Response(tokens, status=status.HTTP_200_OK)


class MFADisableView(APIView):
    """
    POST /auth/mfa/disable/

    Platform admin only (is_staff=True).
    Deletes the TOTPDevice for the target user.
    Body: {user_id: "<uuid>"}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return Response(
                {"error": "Apenas administradores podem desativar MFA."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"error": "user_id é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_user_id = uuid.UUID(str(user_id))
        except (ValueError, AttributeError):
            return Response(
                {"error": "user_id inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_user = User.objects.get(id=target_user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Usuário não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        deleted_count, _ = target_user.totp_device.__class__.objects.filter(
            user=target_user
        ).delete()

        if deleted_count == 0:
            return Response(
                {"message": "MFA não estava configurado para este usuário."},
                status=status.HTTP_200_OK,
            )

        logger.info(
            "MFA disabled for user %s by admin %s",
            target_user.id,
            request.user.id,
        )
        return Response(
            {"message": "MFA desativado com sucesso."},
            status=status.HTTP_200_OK,
        )
