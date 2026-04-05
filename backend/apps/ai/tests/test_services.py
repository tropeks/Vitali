"""
Tests for TUSSCoder service.
Uses TenantTestCase so tenant DB context is available.
"""
import json
from unittest.mock import MagicMock, patch

from django_tenants.test.cases import TenantTestCase
from django.core.cache import cache
from django.test import override_settings

from apps.ai.models import AIPromptTemplate, AIUsageLog, TUSSAISuggestion
from apps.core.models import TenantAIConfig


def _make_template(tenant_context):
    return AIPromptTemplate.objects.create(
        name='tuss_suggest',
        version=1,
        is_active=True,
        system_prompt='You are a billing assistant.',
        user_prompt_template='Guide: {guide_type}\nDesc: {description}\nCandidates:\n{candidates}\nReturn JSON only.',
    )


def _mock_tuss_codes(codes):
    """Return mock TUSSCode-like objects."""
    mocks = []
    for i, (code, desc) in enumerate(codes):
        m = MagicMock()
        m.code = code
        m.description = desc
        m.id = i + 1  # Real integer so tuss_code_id can be pickled for Redis cache
        mocks.append(m)
    return mocks


class TUSSCoderTest(TenantTestCase):

    def setUp(self):
        cache.clear()
        self._override = override_settings(ANTHROPIC_API_KEY="test-key", FEATURE_AI_TUSS=True, AI_RATE_LIMIT_PER_HOUR=1000)
        self._override.enable()
        TenantAIConfig.objects.update_or_create(
            tenant=self.__class__.tenant,
            defaults={"ai_tuss_enabled": True, "rate_limit_per_hour": 1000},
        )
        self.template = _make_template(None)
        self.tenant_schema = self.tenant.schema_name

    def tearDown(self):
        self._override.disable()

    def _claude_response(self, codes):
        """Return mock ClaudeGateway.complete result for given codes."""
        suggestions = [{"code": c} for c in codes]
        return json.dumps({"suggestions": suggestions}), 50, 20

    def test_drops_hallucinated_code(self):
        """Codes not in retrieval candidates must be dropped."""
        candidates = _mock_tuss_codes([("10101012", "Consulta cardiologia")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012", "99999999"])):
            from apps.ai.services import suggest
            result = suggest("consulta", "consulta", self.tenant_schema)

        codes = [s.tuss_code for s in result.suggestions]
        self.assertIn("10101012", codes)
        self.assertNotIn("99999999", codes)
        self.assertFalse(result.degraded)

    def test_returns_empty_when_no_candidates(self):
        """If retrieval returns nothing, LLM must NOT be called."""
        with patch("apps.ai.services._retrieve_candidates", return_value=[]), \
             patch("apps.ai.gateway.ClaudeGateway.complete") as mock_claude:
            from apps.ai.services import suggest
            result = suggest("xyzxyz", "consulta", self.tenant_schema)

        mock_claude.assert_not_called()
        self.assertEqual(result.suggestions, [])
        self.assertFalse(result.degraded)
        self.assertEqual(AIUsageLog.objects.filter(event_type='zero_result').count(), 1)

    def test_trigram_fallback_fires(self):
        """When full-text search returns 0, trigram fallback should be tried."""
        candidates = _mock_tuss_codes([("10101012", "Consulta cardiologia")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])):
            from apps.ai.services import suggest
            result = suggest("cardio consulta", "consulta", self.tenant_schema)

        self.assertEqual(len(result.suggestions), 1)

    def test_creates_suggestion_records(self):
        """A successful call must create TUSSAISuggestion records."""
        candidates = _mock_tuss_codes([
            ("10101012", "Consulta cardiologia"),
            ("10101039", "Consulta por telemedicina"),
        ])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012", "10101039"])):
            from apps.ai.services import suggest
            result = suggest("consulta cardiologia", "consulta", self.tenant_schema)

        self.assertEqual(TUSSAISuggestion.objects.count(), 2)

    def test_graceful_degradation_on_llm_error(self):
        """LLM failure must return degraded=True, not raise."""
        candidates = _mock_tuss_codes([("10101012", "Consulta")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", side_effect=Exception("Claude 500")):
            from apps.ai.services import suggest
            result = suggest("consulta", "consulta", self.tenant_schema)

        self.assertTrue(result.degraded)
        self.assertEqual(result.suggestions, [])

    def test_validation_dropout_logged(self):
        """If Claude returns only invalid codes, log as validation_dropout."""
        candidates = _mock_tuss_codes([("10101012", "Consulta")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["99999999"])):
            from apps.ai.services import suggest
            result = suggest("consulta", "consulta", self.tenant_schema)

        self.assertEqual(result.suggestions, [])
        self.assertFalse(result.degraded)
        self.assertEqual(AIUsageLog.objects.filter(event_type='validation_dropout').count(), 1)

    def test_cache_hit_skips_claude(self):
        """Second call with same input must return cached result, Claude not called."""
        candidates = _mock_tuss_codes([("10101012", "Consulta")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])) as mock_claude:
            from apps.ai.services import suggest
            result1 = suggest("consulta", "consulta", self.tenant_schema)
            result2 = suggest("consulta", "consulta", self.tenant_schema)

        self.assertEqual(mock_claude.call_count, 1)
        self.assertFalse(result1.cached)
        self.assertTrue(result2.cached)

    def test_tenant_cache_isolation(self):
        """Tenant A's cached response must not be served to tenant B."""
        candidates = _mock_tuss_codes([("10101012", "Consulta")])
        enabled_config = TenantAIConfig(ai_tuss_enabled=True, rate_limit_per_hour=1000)

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.services.get_tenant_ai_config", return_value=enabled_config), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])) as mock_claude:
            from apps.ai.services import suggest
            suggest("consulta", "consulta", "tenant_a")
            suggest("consulta", "consulta", "tenant_b")

        self.assertEqual(mock_claude.call_count, 2)

    def test_guide_type_partitioning(self):
        """Same description + different guide_type must produce separate cache entries."""
        candidates = _mock_tuss_codes([("10101012", "Consulta")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])) as mock_claude:
            from apps.ai.services import suggest
            suggest("consulta", "consulta", self.tenant_schema)
            suggest("consulta", "sadt", self.tenant_schema)

        self.assertEqual(mock_claude.call_count, 2)

    def test_prompt_version_invalidates_cache(self):
        """Bumping prompt version must cause cache miss."""
        candidates = _mock_tuss_codes([("10101012", "Consulta")])

        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])) as mock_claude:
            from apps.ai.services import suggest
            suggest("consulta", "consulta", self.tenant_schema)
            # Bump version
            self.template.version = 2
            self.template.save()
            suggest("consulta", "consulta", self.tenant_schema)

        self.assertEqual(mock_claude.call_count, 2)
