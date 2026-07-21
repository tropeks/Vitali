"""
Shared invitation issuance (S-076 / S-132).

A single chokepoint for minting the 72h signed *password_set* token, persisting
a :class:`~apps.core.models.UserInvitation` (storing only the SHA-256 hash of the
token, so a DB leak never exposes a live token), and sending the welcome email.

Used by:
  - apps.core.views._create_invitation_for_user  (admin invites a staff user)
  - apps.core.services.provisioning              (self-serve clinic owner welcome)

The ``tenant`` is passed explicitly rather than read from ``connection`` so the
helper works from the public schema (self-serve signup runs there, before the
owner has ever logged into their clinic's schema).
"""

import hashlib
import logging
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

INVITATION_TTL_HOURS = 72


def build_password_set_link(token: str) -> str:
    """Frontend URL the invited user opens to choose their password."""
    base = getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/auth/set-password/{token}"


def issue_password_set_invitation(user, *, tenant=None, created_by=None):
    """
    Mint a password-set token for *user*, persist the invitation, and email it.

    Returns ``(invitation, token)``. Never raises on email failure — the email
    service swallows and logs its own errors so a transient SMTP outage doesn't
    abort tenant provisioning.
    """
    from apps.core.models import UserInvitation
    from apps.core.services.email import EmailService

    expires_at = timezone.now() + timedelta(hours=INVITATION_TTL_HOURS)
    payload = {
        "user_id": str(user.id),
        "purpose": "password_set",
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    invitation = UserInvitation.objects.create(
        user=user,
        tenant=tenant,
        created_by=created_by,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    EmailService.send_user_invitation(user, build_password_set_link(token))
    logger.info(
        "invitation.issued user=%s tenant=%s",
        user.id,
        getattr(tenant, "schema_name", None),
    )
    return invitation, token
