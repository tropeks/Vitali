"""
Tests for the Phase 3 i18n infrastructure (multi-country):
- `preferred_language` field on User
- `GET / PATCH /api/v1/users/me/language/` endpoint
- `PreferredLanguageMiddleware` activates the user's language per request
"""

from __future__ import annotations

from django.conf import settings
from django.utils import translation
from rest_framework.test import APIClient

from apps.core.middleware import PreferredLanguageMiddleware
from apps.core.models import Role, User
from apps.test_utils import TenantTestCase

LANG_URL = "/api/v1/users/me/language/"


def _make_user(*, email: str, preferred_language: str = "") -> User:
    role, _ = Role.objects.get_or_create(
        name="i18n_role", defaults={"permissions": ["patients.read"]}
    )
    user = User.objects.create_user(email=email, password="pw", full_name="Test User", role=role)
    if preferred_language:
        user.preferred_language = preferred_language
        user.save(update_fields=["preferred_language"])
    return user


class I18nSettingsTest(TenantTestCase):
    def test_settings_advertise_four_languages(self):
        codes = {c for c, _ in settings.LANGUAGES}
        self.assertEqual(codes, {"pt-br", "pt-pt", "es", "en"})

    def test_default_language_is_pt_br(self):
        self.assertEqual(settings.LANGUAGE_CODE, "pt-br")

    def test_locale_paths_include_backend_locale(self):
        self.assertTrue(any(str(p).endswith("locale") for p in settings.LOCALE_PATHS))


class MeLanguageEndpointTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.user = _make_user(email="lang_user@test.com")
        self.client.force_authenticate(user=self.user)

    def test_get_returns_current_and_supported_languages(self):
        resp = self.client.get(LANG_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["preferred_language"], "")
        codes = {entry["code"] for entry in resp.data["supported_languages"]}
        self.assertEqual(codes, {"pt-br", "pt-pt", "es", "en"})
        self.assertEqual(resp.data["default"], "pt-br")

    def test_patch_persists_supported_code(self):
        resp = self.client.patch(LANG_URL, {"preferred_language": "es"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["preferred_language"], "es")
        self.user.refresh_from_db()
        self.assertEqual(self.user.preferred_language, "es")

    def test_patch_rejects_unknown_code(self):
        resp = self.client.patch(LANG_URL, {"preferred_language": "fr"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unsupported", resp.data["detail"])
        self.assertIn("allowed", resp.data)

    def test_patch_empty_string_resets_to_default(self):
        self.user.preferred_language = "pt-pt"
        self.user.save(update_fields=["preferred_language"])
        resp = self.client.patch(LANG_URL, {"preferred_language": ""}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["preferred_language"], "")
        self.user.refresh_from_db()
        self.assertEqual(self.user.preferred_language, "")

    def test_get_requires_auth(self):
        self.client.logout()
        resp = self.client.get(LANG_URL)
        self.assertIn(resp.status_code, [401, 403])


class PreferredLanguageMiddlewareTest(TenantTestCase):
    """
    Exercise the middleware in isolation — verify that an authenticated user
    with a preferred_language activates it via `translation.get_language()`
    inside the view, and that the activation is unwound after the request.
    """

    def setUp(self):
        # Anchor the test outside any prior activation so deactivate-after
        # observations are clean.
        translation.deactivate_all()

    def tearDown(self):
        translation.deactivate_all()

    def test_authenticated_user_with_pref_activates_language(self):
        captured = {}

        def view(_request):
            captured["lang"] = translation.get_language()
            from django.http import HttpResponse

            return HttpResponse("ok")

        middleware = PreferredLanguageMiddleware(view)

        class _Req:
            class _User:
                is_authenticated = True
                preferred_language = "es"

            user = _User()

        middleware(_Req())
        self.assertEqual(captured["lang"], "es")
        # Activation must be unwound after the request.
        self.assertNotEqual(translation.get_language(), "es")

    def test_authenticated_user_without_pref_keeps_outer_language(self):
        # Make sure we have an unambiguous outer language so the assertion is
        # not biased by prior test state.
        translation.activate("pt-br")
        captured = {}

        def view(_request):
            captured["lang"] = translation.get_language()
            from django.http import HttpResponse

            return HttpResponse("ok")

        middleware = PreferredLanguageMiddleware(view)

        class _Req:
            class _User:
                is_authenticated = True
                preferred_language = ""

            user = _User()

        middleware(_Req())
        self.assertEqual(captured["lang"], "pt-br")

    def test_anonymous_request_is_passthrough(self):
        captured = {}

        def view(_request):
            captured["called"] = True
            from django.http import HttpResponse

            return HttpResponse("ok")

        middleware = PreferredLanguageMiddleware(view)

        class _Req:
            user = None

        middleware(_Req())
        self.assertTrue(captured["called"])
