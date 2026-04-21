"""
Tests for S-064 CID-10 AI Suggester.

Tests:
  - CID10Code queries public schema
  - Cache key includes schema_name
  - Accept updates encounter CID10 field
  - Hallucinated code is filtered out
  - Feature flag OFF returns empty suggestions
"""
import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from apps.test_utils import TenantTestCase


class TestCID10Suggester(TenantTestCase):

    def setUp(self):
        import datetime
        from apps.core.models import CID10Code
        from apps.emr.models import Patient, Professional, Encounter
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        User = get_user_model()

        # Create test CID10 codes (test DB = public schema in test env)
        CID10Code.objects.using("default").get_or_create(
            code="J18.9",
            defaults={"description": "Pneumonia não especificada", "active": True},
        )
        CID10Code.objects.using("default").get_or_create(
            code="J06.9",
            defaults={"description": "Infecção aguda das vias aéreas superiores", "active": True},
        )

        self.user = User.objects.create_user(
            email="cid10_test@clinic.test",
            password="TestPass123!",
            full_name="CID Doctor",
        )
        self.patient = Patient.objects.create(
            full_name="CID Test Patient",
            cpf="555.444.333-22",
            birth_date=datetime.date(1990, 1, 1),
            gender="M",
        )
        self.professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="654321",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            encounter_date=timezone.now(),
        )
        cache.clear()

    def test_cid10code_queries_public_schema(self):
        """CID10Code must always be queried from the public schema."""
        from apps.core.models import CID10Code

        # Query from public schema — should find our test codes
        codes = CID10Code.objects.using("default").filter(active=True).values_list("code", flat=True)
        self.assertIn("J18.9", codes)
        self.assertIn("J06.9", codes)

    def test_cache_key_includes_schema_name(self):
        """The cache key for CID10 suggestions must include schema_name."""
        from apps.ai.services_cid10 import _cache_key

        key_tenant_a = _cache_key("tenant_a", "pneumonia")
        key_tenant_b = _cache_key("tenant_b", "pneumonia")

        # Same query text, different schemas → different keys (LGPD isolation)
        self.assertNotEqual(key_tenant_a, key_tenant_b)
        self.assertIn("tenant_a", key_tenant_a)
        self.assertIn("tenant_b", key_tenant_b)
        self.assertTrue(key_tenant_a.startswith("ai:cid10:tenant_a:"))

    def test_accept_updates_encounter_cid10_field(self):
        """CID10AcceptView updates AICIDSuggestion.accepted_code."""
        from apps.emr.models import AICIDSuggestion
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        client = APIClient()
        client.defaults['SERVER_NAME'] = self.__class__.domain.domain
        refresh = RefreshToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        suggestion = AICIDSuggestion.objects.create(
            encounter=self.encounter,
            query_text="pneumonia bacteriana",
            suggestions=[{"code": "J18.9", "description": "Pneumonia não especificada", "confidence": 90}],
        )

        response = client.post(
            f"/api/v1/encounters/{self.encounter.id}/cid10-accept/",
            {"suggestion_id": str(suggestion.id), "code": "J18.9"},
        )
        self.assertEqual(response.status_code, 200)

        suggestion.refresh_from_db()
        self.assertEqual(suggestion.accepted_code, "J18.9")

    def test_hallucinated_code_filtered(self):
        """
        If LLM returns a code not in CID10Code DB, it must be filtered out.
        """
        from apps.ai.services_cid10 import _validate_codes

        # FAKE_CODE does not exist in DB
        raw_suggestions = [
            {"code": "J18.9", "description": "Pneumonia", "confidence": 90},
            {"code": "FAKE123", "description": "Hallucinated code", "confidence": 80},
        ]
        validated = _validate_codes(raw_suggestions)
        codes = [s.code for s in validated]
        self.assertIn("J18.9", codes)
        self.assertNotIn("FAKE123", codes)

    def test_feature_flag_off_returns_empty(self):
        """When ai_cid10_suggest feature flag is OFF, returns empty suggestions."""
        from apps.ai.services_cid10 import CID10Suggester

        with patch("apps.ai.services_cid10.get_tenant_ai_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(ai_cid10_suggest=False)
            suggester = CID10Suggester()
            result = suggester.suggest("pneumonia bacteriana grave", "test_schema")

        self.assertEqual(result.suggestions, [])
        self.assertFalse(result.degraded)

    def test_suggest_returns_cached_on_second_call(self):
        """Second call with same text/schema returns cached=True."""
        from apps.ai.services_cid10 import CID10Suggester

        mock_response = json.dumps([
            {"code": "J18.9", "description": "Pneumonia não especificada", "confidence": 88}
        ])

        with patch("apps.ai.services_cid10.get_tenant_ai_config") as mock_cfg, \
             patch("apps.ai.services_cid10.is_rate_limited", return_value=False), \
             patch("apps.ai.services_cid10.is_open", return_value=False), \
             patch("apps.ai.services_cid10._retrieve_candidates") as mock_cands, \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=(mock_response, 100, 50)):
            mock_cfg.return_value = MagicMock(
                ai_cid10_suggest=True,
                rate_limit_per_hour=500,
            )
            mock_cands.return_value = [
                {"code": "J18.9", "description": "Pneumonia não especificada"}
            ]
            cache.clear()

            suggester = CID10Suggester()
            result1 = suggester.suggest("pneumonia", "test_schema")
            self.assertFalse(result1.cached)
            self.assertTrue(len(result1.suggestions) > 0)

            result2 = suggester.suggest("pneumonia", "test_schema")
            self.assertTrue(result2.cached)

    def test_suggest_endpoint_returns_empty_for_short_text(self):
        """POST to cid10-suggest with < 15 chars returns empty suggestions."""
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        client = APIClient()
        client.defaults['SERVER_NAME'] = self.__class__.domain.domain
        refresh = RefreshToken.for_user(self.user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        response = client.post(
            f"/api/v1/encounters/{self.encounter.id}/cid10-suggest/",
            {"text": "grippe"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestions"], [])
