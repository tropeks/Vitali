"""
Unit tests for SMART-on-FHIR helpers (``apps.fhir.services.smart``):
scope filtering and PKCE verification. No DB/tenant required.
"""

from __future__ import annotations

import base64
import hashlib

from apps.fhir.services import smart


class _FakeClient:
    """Minimal stand-in for SmartClient.allowed_scopes()."""

    def __init__(self, scopes):
        self._scopes = set(scopes)

    def allowed_scopes(self):
        return self._scopes


# ─── filter_requested_scopes ─────────────────────────────────────────────────


def test_unsupported_scopes_are_dropped():
    granted = smart.filter_requested_scopes(
        "patient/*.read system/*.write made-up", client=_FakeClient([])
    )
    assert granted == "patient/*.read"


def test_client_without_explicit_scopes_may_request_any_supported():
    granted = smart.filter_requested_scopes("openid patient/*.read", client=_FakeClient([]))
    assert set(granted.split()) == {"openid", "patient/*.read"}


def test_client_scopes_restrict_grant():
    client = _FakeClient(["patient/*.read"])
    granted = smart.filter_requested_scopes("openid patient/*.read user/*.read", client=client)
    # Only patient/*.read is both supported AND allowed for this client.
    assert granted == "patient/*.read"


def test_empty_request_grants_nothing():
    assert smart.filter_requested_scopes("", client=_FakeClient([])) == ""


# ─── verify_pkce ─────────────────────────────────────────────────────────────


def _s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_s256_roundtrip_succeeds():
    verifier = "a-long-random-verifier-string-1234567890"
    challenge = _s256_challenge(verifier)
    assert smart.verify_pkce(code_challenge=challenge, method="S256", verifier=verifier) is True


def test_s256_wrong_verifier_fails():
    challenge = _s256_challenge("correct-verifier")
    assert smart.verify_pkce(code_challenge=challenge, method="S256", verifier="wrong") is False


def test_plain_method_compares_verbatim():
    assert smart.verify_pkce(code_challenge="abc123", method="plain", verifier="abc123") is True
    assert smart.verify_pkce(code_challenge="abc123", method="plain", verifier="nope") is False


def test_missing_challenge_or_verifier_fails():
    assert smart.verify_pkce(code_challenge="", method="S256", verifier="x") is False
    assert smart.verify_pkce(code_challenge="abc", method="S256", verifier="") is False


def test_supported_scopes_are_read_only():
    # The FHIR surface is read-only: no write/* scopes should ever be advertised.
    assert not any(".write" in s for s in smart.SUPPORTED_SCOPES)
    assert "patient/*.read" in smart.SUPPORTED_SCOPES
