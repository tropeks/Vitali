"""Regression tests for user invitation token issuance."""

from unittest.mock import patch

import jwt
from django.conf import settings
from django.utils import timezone

from apps.core.models import User, UserInvitation
from apps.core.views import _create_invitation_for_user
from apps.test_utils import TenantTestCase


class UserInvitationTokenTests(TenantTestCase):
    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_repeated_invites_for_same_user_in_same_second_have_unique_tokens(self, mock_send):
        admin = User.objects.create_superuser(
            email="admin.invite@test.com",
            password="AdminPass1!",
            full_name="Invite Admin",
        )
        invitee = User.objects.create_user(
            email="invitee.repeat@test.com",
            full_name="Repeat Invitee",
        )
        fixed_now = timezone.now()

        with patch("apps.core.views.timezone.now", return_value=fixed_now):
            first_invitation, first_token = _create_invitation_for_user(
                invitee,
                requesting_user=admin,
            )
            second_invitation, second_token = _create_invitation_for_user(
                invitee,
                requesting_user=admin,
            )

        first_payload = jwt.decode(first_token, settings.SECRET_KEY, algorithms=["HS256"])
        second_payload = jwt.decode(second_token, settings.SECRET_KEY, algorithms=["HS256"])

        self.assertNotEqual(first_token, second_token)
        self.assertNotEqual(first_payload["jti"], second_payload["jti"])
        self.assertNotEqual(first_invitation.token_hash, second_invitation.token_hash)
        self.assertEqual(UserInvitation.objects.filter(user=invitee).count(), 2)
        self.assertEqual(mock_send.call_count, 2)
