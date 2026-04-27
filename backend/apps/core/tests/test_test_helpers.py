"""
S-084: Tests for the test-only IssueInvitationTokenView endpoint and Django
system check.

Covers:
- test_issue_token_endpoint_returns_404_when_e2e_mode_off
- test_issue_token_endpoint_returns_404_when_db_name_not_test_suffix
- test_issue_token_endpoint_returns_403_for_non_superuser
- test_issue_token_endpoint_returns_token_for_superuser_in_e2e_mode
- test_returned_token_works_with_set_password_endpoint
- test_system_check_fails_when_e2e_mode_with_non_test_db

Run: pytest apps/core/tests/test_test_helpers.py -v
"""

from __future__ import annotations

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import Role, User, UserInvitation
from apps.test_utils import TenantTestCase

# ─── Helpers ──────────────────────────────────────────────────────────────────

_TEST_DB_SETTINGS = {
    "default": {
        **settings.DATABASES["default"],
        "NAME": "vitali_test",
    }
}


def _make_user(email="e2e.invitee@example.com", full_name="E2E Invitee"):
    return User.objects.create_user(
        email=email,
        password=None,
        full_name=full_name,
    )


def _make_superuser(email="e2e.super@example.com"):
    role, _ = Role.objects.get_or_create(name="e2e-super", defaults={"permissions": ["admin"]})
    return User.objects.create_superuser(
        email=email,
        password="Super123!",
        full_name="E2E Superuser",
    )


def _make_regular_user(email="e2e.regular@example.com"):
    role, _ = Role.objects.get_or_create(name="e2e-regular", defaults={"permissions": []})
    return User.objects.create_user(
        email=email,
        password="Regular123!",
        full_name="E2E Regular",
        role=role,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


class IssueInvitationTokenViewTests(TenantTestCase):
    """Test cases for IssueInvitationTokenView (S-084)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.superuser = _make_superuser()
        self.regular_user = _make_regular_user()
        self.invitee = _make_user()

    # ── 1: E2E_MODE off → 404 ─────────────────────────────────────────────────

    @override_settings(E2E_MODE=False)
    def test_issue_token_endpoint_returns_404_when_e2e_mode_off(self):
        """When E2E_MODE=False the endpoint returns 404 regardless of other params."""
        self.client.force_authenticate(user=self.superuser)
        resp = self.client.post(
            "/api/v1/_test/invitations/issue-token/",
            {"user_email": self.invitee.email},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    # ── 2: E2E_MODE on but DB name not _test suffix → 404 ────────────────────

    @override_settings(
        E2E_MODE=True,
        DATABASES={
            "default": {
                **settings.DATABASES["default"],
                "NAME": "vitali_production",
            }
        },
    )
    def test_issue_token_endpoint_returns_404_when_db_name_not_test_suffix(self):
        """When DB name doesn't end with _test the endpoint returns 404."""
        self.client.force_authenticate(user=self.superuser)
        resp = self.client.post(
            "/api/v1/_test/invitations/issue-token/",
            {"user_email": self.invitee.email},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    # ── 3: E2E_MODE on + _test DB but non-superuser → 403 ────────────────────

    @override_settings(E2E_MODE=True, DATABASES=_TEST_DB_SETTINGS)
    def test_issue_token_endpoint_returns_403_for_non_superuser(self):
        """Regular (non-superuser) gets 403 even when E2E_MODE is active."""
        self.client.force_authenticate(user=self.regular_user)
        resp = self.client.post(
            "/api/v1/_test/invitations/issue-token/",
            {"user_email": self.invitee.email},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Superuser required", resp.json()["error"])

    # ── 4: happy path — superuser + E2E_MODE + _test DB → token ──────────────

    @override_settings(E2E_MODE=True, DATABASES=_TEST_DB_SETTINGS)
    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_issue_token_endpoint_returns_token_for_superuser_in_e2e_mode(self, mock_send):
        """Superuser in E2E_MODE gets back a token + invitation_id."""
        self.client.force_authenticate(user=self.superuser)
        resp = self.client.post(
            "/api/v1/_test/invitations/issue-token/",
            {"user_email": self.invitee.email},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.json()
        self.assertIn("token", data)
        self.assertIn("invitation_id", data)
        self.assertTrue(len(data["token"]) > 10)

        # A fresh UserInvitation row was created
        invitation = UserInvitation.objects.get(id=data["invitation_id"])
        self.assertEqual(invitation.user, self.invitee)
        self.assertFalse(invitation.is_consumed)

    # ── 5: returned token works with set-password endpoint ────────────────────

    @override_settings(E2E_MODE=True, DATABASES=_TEST_DB_SETTINGS)
    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_returned_token_works_with_set_password_endpoint(self, mock_send):
        """Token returned by the test endpoint can be used with set-password."""
        # Step 1: get a fresh token
        self.client.force_authenticate(user=self.superuser)
        issue_resp = self.client.post(
            "/api/v1/_test/invitations/issue-token/",
            {"user_email": self.invitee.email},
            format="json",
        )
        self.assertEqual(issue_resp.status_code, 200, issue_resp.data)
        token = issue_resp.json()["token"]

        # Step 2: use token with set-password (no auth required)
        anon_client = APIClient()
        anon_client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        set_pw_resp = anon_client.post(
            f"/api/v1/auth/set-password/{token}/",
            {"password": "NewPass123!"},
            format="json",
        )
        self.assertEqual(set_pw_resp.status_code, 200, set_pw_resp.data)
        data = set_pw_resp.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)


# ─── _e2e_mode_safe helper tests ──────────────────────────────────────────────


class E2EModeSafeHelperTests(TenantTestCase):
    """Unit tests for the _e2e_mode_safe() helper function."""

    def test_returns_false_when_e2e_mode_off(self):
        from apps.core.views_test_helpers import _e2e_mode_safe

        with override_settings(E2E_MODE=False):
            self.assertFalse(_e2e_mode_safe())

    def test_returns_false_when_db_name_not_test_suffix(self):
        from apps.core.views_test_helpers import _e2e_mode_safe

        with override_settings(
            E2E_MODE=True,
            DATABASES={"default": {"NAME": "vitali_production"}},
        ):
            self.assertFalse(_e2e_mode_safe())

    def test_returns_true_when_e2e_mode_on_and_db_ends_with_test(self):
        from apps.core.views_test_helpers import _e2e_mode_safe

        with override_settings(
            E2E_MODE=True,
            DATABASES={"default": {"NAME": "vitali_test"}},
        ):
            self.assertTrue(_e2e_mode_safe())


# ─── System check tests ───────────────────────────────────────────────────────


class SystemCheckTests(TenantTestCase):
    """Tests for the Django system check that guards E2E_MODE misconfiguration."""

    def test_system_check_passes_when_e2e_mode_off(self):
        from apps.core.checks import check_e2e_mode_only_on_test_db

        with override_settings(E2E_MODE=False):
            errors = check_e2e_mode_only_on_test_db(None)
        self.assertEqual(errors, [])

    def test_system_check_fails_when_e2e_mode_with_non_test_db(self):
        """Error core.E001 raised when E2E_MODE=True but DB name doesn't end with _test."""
        from apps.core.checks import check_e2e_mode_only_on_test_db

        with override_settings(
            E2E_MODE=True,
            DATABASES={"default": {"NAME": "vitali"}},
            SECRET_KEY="dev-short-key",
        ):
            errors = check_e2e_mode_only_on_test_db(None)

        error_ids = [e.id for e in errors]
        self.assertIn("core.E001", error_ids)

    def test_system_check_passes_when_e2e_mode_with_test_db(self):
        """No error when E2E_MODE=True and DB name ends with _test."""
        from apps.core.checks import check_e2e_mode_only_on_test_db

        with override_settings(
            E2E_MODE=True,
            DATABASES={"default": {"NAME": "vitali_test"}},
            SECRET_KEY="dev-short-key",
        ):
            errors = check_e2e_mode_only_on_test_db(None)

        error_ids = [e.id for e in errors]
        self.assertNotIn("core.E001", error_ids)

    def test_system_check_emits_warning_for_production_grade_secret_key(self):
        """Warning core.W001 emitted when E2E_MODE=True with a long non-dev SECRET_KEY."""
        from apps.core.checks import check_e2e_mode_only_on_test_db

        # A key >= 50 chars that doesn't start with test-/dev-/django-insecure-
        long_prod_key = "x" * 50

        with override_settings(
            E2E_MODE=True,
            DATABASES={"default": {"NAME": "vitali_test"}},
            SECRET_KEY=long_prod_key,
        ):
            errors = check_e2e_mode_only_on_test_db(None)

        warning_ids = [e.id for e in errors]
        self.assertIn("core.W001", warning_ids)
