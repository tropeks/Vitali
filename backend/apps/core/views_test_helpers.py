"""
Test-only helpers — protected by triple-layer gate (E2E_MODE + superuser + _test DB suffix).

These endpoints exist solely to support automated E2E tests. They MUST NOT
be reachable in production. Three independent gates protect them:
  1. settings.E2E_MODE = True (env var, never set in deploy pipelines)
  2. request.user.is_superuser
  3. settings.DATABASES['default']['NAME'] ends with '_test'

Plus a Django system check (apps/core/checks.py) FAILS the deploy if
E2E_MODE=True AND DB-name does not end with '_test'.
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _e2e_mode_safe() -> bool:
    """Triple-gate: E2E_MODE on, DB-name ends with _test."""
    if not getattr(settings, "E2E_MODE", False):
        return False
    db_name = settings.DATABASES.get("default", {}).get("NAME", "")
    return str(db_name).endswith("_test")


class IssueInvitationTokenView(APIView):
    """
    POST /api/v1/_test/invitations/issue-token/

    Body: {"user_email": "..."}
    Returns: {"token": "<jwt>"} for an existing User (must already exist; doesn't
             create the User row, only the UserInvitation + signed JWT).

    Security: triple-gated as documented above. Returns 404 in production.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Gate 1+3: E2E_MODE + DB suffix
        if not _e2e_mode_safe():
            return Response(status=status.HTTP_404_NOT_FOUND)
        # Gate 2: superuser only
        if not request.user.is_superuser:
            return Response(
                {"error": "Superuser required for test endpoint"},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_email = request.data.get("user_email")
        if not user_email:
            return Response({"error": "user_email required"}, status=400)

        from apps.core.models import User

        try:
            user = User.objects.get(email=user_email)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Mint a fresh invitation + token (same path admins use)
        from apps.core.views import _create_invitation_for_user

        invitation, token = _create_invitation_for_user(user, requesting_user=request.user)

        logger.warning(
            "TEST-ONLY endpoint issued invitation token for user_email=%s — "
            "this should NEVER appear in production logs",
            user_email,
        )
        return Response(
            {
                "token": token,
                "invitation_id": str(invitation.id),
            }
        )
