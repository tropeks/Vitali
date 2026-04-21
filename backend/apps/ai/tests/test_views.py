"""
Tests for AI views — TUSSSuggestView, TUSSSuggestFeedbackView, AIUsageView.
"""
import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings, TestCase
from apps.test_utils import TenantTestCase
from rest_framework.test import APIClient

from apps.ai.models import AIPromptTemplate, AIUsageLog, TUSSAISuggestion
from apps.core.models import FeatureFlag, Role, TenantAIConfig, User


def _make_user(schema_domain, role_name="faturista"):
    role, _ = Role.objects.get_or_create(
        name=role_name,
        defaults={"permissions": ["billing.read", "billing.write", "billing.full", "emr.read", "ai.use", "users.read"]},
    )
    user = User.objects.create_user(
        email=f"test_{role_name}@test.com",
        password="pw",
        role=role,
    )
    return user


def _make_template():
    return AIPromptTemplate.objects.create(
        name='tuss_suggest',
        version=1,
        is_active=True,
        system_prompt='You are a billing assistant.',
        user_prompt_template='Guide: {guide_type}\nDesc: {description}\nCandidates:\n{candidates}\nReturn JSON only.',
    )


def _mock_candidates(codes):
    mocks = []
    for i, (code, desc) in enumerate(codes):
        m = MagicMock()
        m.code = code
        m.description = desc
        m.id = i + 1  # Real integer so tuss_code_id can be pickled for Redis cache
        mocks.append(m)
    return mocks


class TUSSSuggestViewTest(TenantTestCase):

    def setUp(self):
        cache.clear()
        self._override = override_settings(FEATURE_AI_TUSS=True, ANTHROPIC_API_KEY="test-key", AI_RATE_LIMIT_PER_HOUR=1000)
        self._override.enable()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='ai_tuss', defaults={'is_enabled': True}
        )
        TenantAIConfig.objects.update_or_create(
            tenant=self.__class__.tenant,
            defaults={"ai_tuss_enabled": True, "rate_limit_per_hour": 1000},
        )
        self.user = _make_user(self.__class__.domain)
        self.client.force_authenticate(user=self.user)
        self.template = _make_template()

    def tearDown(self):
        self._override.disable()

    def _claude_response(self, codes):
        suggestions = [{"code": c} for c in codes]
        return json.dumps({"suggestions": suggestions}), 50, 20

    def test_feature_flag_off_returns_degraded(self):
        """FEATURE_AI_TUSS=False returns 200 with a detail message (not 404 — avoids confusing users)."""
        with override_settings(FEATURE_AI_TUSS=False):
            resp = self.client.post('/api/v1/ai/tuss-suggest/', {'description': 'consulta'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('detail', resp.data)

    def test_returns_suggestions_on_success(self):
        candidates = _mock_candidates([("10101012", "Consulta em consultório")])
        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])):
            resp = self.client.post('/api/v1/ai/tuss-suggest/', {'description': 'consulta cardiologia', 'guide_type': 'consulta'}, format='json')

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['suggestions']), 1)
        self.assertEqual(data['suggestions'][0]['tuss_code'], '10101012')
        self.assertFalse(data['degraded'])

    def test_cache_hit_returns_cached_true(self):
        candidates = _mock_candidates([("10101012", "Consulta em consultório")])
        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])) as mock_claude:
            self.client.post('/api/v1/ai/tuss-suggest/', {'description': 'consulta', 'guide_type': 'consulta'}, format='json')
            resp2 = self.client.post('/api/v1/ai/tuss-suggest/', {'description': 'consulta', 'guide_type': 'consulta'}, format='json')

        self.assertEqual(mock_claude.call_count, 1)
        self.assertTrue(resp2.json()['cached'])

    def test_degraded_on_claude_error(self):
        candidates = _mock_candidates([("10101012", "Consulta")])
        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.gateway.ClaudeGateway.complete", side_effect=Exception("500")):
            resp = self.client.post('/api/v1/ai/tuss-suggest/', {'description': 'consulta', 'guide_type': 'consulta'}, format='json')

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['degraded'])
        self.assertEqual(data['suggestions'], [])

    def test_unauthenticated_returns_401(self):
        anon_client = APIClient()
        anon_client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        resp = anon_client.post('/api/v1/ai/tuss-suggest/', {'description': 'consulta'}, format='json')
        self.assertIn(resp.status_code, [401, 403])

    def test_tenant_cache_isolation(self):
        """Requests from different schemas produce separate cache entries."""
        candidates = _mock_candidates([("10101012", "Consulta")])
        enabled_config = TenantAIConfig(ai_tuss_enabled=True, rate_limit_per_hour=1000)
        with patch("apps.ai.services._retrieve_candidates", return_value=candidates), \
             patch("apps.ai.services.get_tenant_ai_config", return_value=enabled_config), \
             patch("apps.ai.gateway.ClaudeGateway.complete", return_value=self._claude_response(["10101012"])) as mock_claude:
            # Same description, different schema
            from apps.ai import services
            services.suggest("consulta", "consulta", "schema_a")
            services.suggest("consulta", "consulta", "schema_b")

        self.assertEqual(mock_claude.call_count, 2)


class TUSSSuggestFeedbackViewTest(TenantTestCase):

    def setUp(self):
        cache.clear()
        self._override = override_settings(FEATURE_AI_TUSS=True, ANTHROPIC_API_KEY="test-key")
        self._override.enable()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key='ai_tuss', defaults={'is_enabled': True}
        )
        self.user = _make_user(self.__class__.domain)
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        self._override.disable()

    def _make_suggestion(self):
        return TUSSAISuggestion.objects.create(
            tuss_code="10101012",
            description="Consulta",
            rank=1,
            input_text="consulta cardiologia",
            guide_type="consulta",
        )

    def test_marks_suggestion_accepted(self):
        suggestion = self._make_suggestion()
        resp = self.client.post('/api/v1/ai/tuss-suggest/feedback/', {
            'suggestion_id': str(suggestion.id),
            'accepted': True,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        suggestion.refresh_from_db()
        self.assertTrue(suggestion.accepted)
        self.assertIsNotNone(suggestion.feedback_at)

    def test_marks_suggestion_rejected(self):
        suggestion = self._make_suggestion()
        resp = self.client.post('/api/v1/ai/tuss-suggest/feedback/', {
            'suggestion_id': str(suggestion.id),
            'accepted': False,
        }, format='json')
        suggestion.refresh_from_db()
        self.assertFalse(suggestion.accepted)

    def test_unknown_suggestion_returns_404(self):
        import uuid
        resp = self.client.post('/api/v1/ai/tuss-suggest/feedback/', {
            'suggestion_id': str(uuid.uuid4()),
            'accepted': True,
        }, format='json')
        self.assertEqual(resp.status_code, 404)


class AIUsageViewTest(TenantTestCase):

    def setUp(self):
        self._override = override_settings(FEATURE_AI_TUSS=True)
        self._override.enable()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        # Create admin user with users.read permission
        role, _ = Role.objects.get_or_create(
            name="admin_ai_test",
            defaults={"permissions": ["users.read", "ai.use"]},
        )
        self.admin = User.objects.create_user(
            email="admin@test.com",
            password="pw",
            role=role,
        )
        # Faturista without users.read
        faturista_role, _ = Role.objects.get_or_create(
            name="faturista_ai_test",
            defaults={"permissions": ["ai.use"]},
        )
        self.faturista = User.objects.create_user(
            email="faturista@test.com",
            password="pw",
            role=faturista_role,
        )
        AIUsageLog.objects.create(event_type='llm_call', tokens_in=50, tokens_out=20, latency_ms=300)

    def test_admin_sees_usage(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/v1/ai/usage/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data['llm_calls'], 1)

    def test_non_admin_gets_403(self):
        self.client.force_authenticate(user=self.faturista)
        resp = self.client.get('/api/v1/ai/usage/')
        self.assertEqual(resp.status_code, 403)

    def tearDown(self):
        self._override.disable()
