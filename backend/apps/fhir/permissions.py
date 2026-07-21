"""
SMART-on-FHIR scope enforcement for the FHIR resource surface.

Access tokens minted by the SMART token endpoint carry ``token_use="smart"``, the
granted ``scope`` and — when the app was launched with patient context — a
``patient`` claim (see ``apps.fhir.services.smart.mint_access_token``). Regular
Vitali logins carry none of these, so for them :class:`SmartScopePermission` is a
no-op and the standard gates (module FeatureFlag + ``fhir.read`` RBAC) are the
whole story.

For SMART tokens the rules are:

- at least one supported read scope must have been granted, otherwise the token
  cannot read any FHIR resource (403);
- ``user/*.read`` grants user-level access — everything the authorizing user's
  RBAC allows, across the whole tenant;
- ``patient/*.read`` *without* ``user/*.read`` confines the token to the patient
  compartment of the launch-context patient: it requires a ``patient`` claim, and
  the views filter every patient-linked resource down to that patient via
  :func:`smart_patient_context`. ``Practitioner`` is exempt (an administrative
  directory resource outside the patient compartment, needed to resolve
  references from Encounters et al.).
"""

from __future__ import annotations

import uuid

from rest_framework.permissions import BasePermission

from apps.core.tenant_auth import SMART_TOKEN_USE, TOKEN_USE_CLAIM

from .services.smart import PATIENT_CLAIM

SCOPE_CLAIM = "scope"
USER_READ_SCOPE = "user/*.read"
PATIENT_READ_SCOPE = "patient/*.read"

# uuid that matches no row — used to fail CLOSED on a malformed patient claim.
_NIL_UUID = uuid.UUID(int=0)


def _token_get(token, key: str, default=None):
    """Read a claim defensively (``request.auth`` may be None or non-JWT)."""
    getter = getattr(token, "get", None)
    if getter is None:
        return default
    return getter(key, default)


def is_smart_token(token) -> bool:
    """True when the validated token was minted by the SMART token endpoint."""
    return _token_get(token, TOKEN_USE_CLAIM) == SMART_TOKEN_USE


def granted_scopes(token) -> set[str]:
    raw = _token_get(token, SCOPE_CLAIM, "") or ""
    return {s for s in str(raw).split() if s}


class SmartScopePermission(BasePermission):
    """Deny SMART tokens lacking a read scope (or patient context when confined)."""

    message = "SMART token does not grant a scope that allows reading this resource."

    def has_permission(self, request, view) -> bool:
        token = getattr(request, "auth", None)
        if not is_smart_token(token):
            return True
        scopes = granted_scopes(token)
        if USER_READ_SCOPE in scopes:
            return True
        if PATIENT_READ_SCOPE in scopes:
            # Patient-level tokens are only usable with a launch patient context.
            return bool(_token_get(token, PATIENT_CLAIM))
        return False


def smart_patient_context(request) -> uuid.UUID | None:
    """The patient UUID every compartment query must be confined to, or ``None``.

    ``None`` means unconfined: not a SMART token, or a SMART token holding the
    user-level read scope. A malformed ``patient`` claim confines to the nil UUID
    (matches nothing) rather than silently widening access.
    """
    token = getattr(request, "auth", None)
    if not is_smart_token(token):
        return None
    if USER_READ_SCOPE in granted_scopes(token):
        return None
    raw = str(_token_get(token, PATIENT_CLAIM, "") or "")
    try:
        return uuid.UUID(raw.rsplit("/", 1)[-1])
    except (ValueError, AttributeError):
        return _NIL_UUID
