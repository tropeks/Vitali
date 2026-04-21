"""
Tests for predict_glosa() service function (S-034).
"""
import json
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from apps.test_utils import TenantTestCase

from apps.ai.models import AIPromptTemplate, GlosaPrediction
from apps.ai.services import PredictionResult, predict_glosa


def _make_glosa_template():
    return AIPromptTemplate.objects.create(
        name="glosa_predict",
        version=1,
        is_active=True,
        system_prompt="You are a claims auditor.",
        user_prompt_template=(
            "TUSS: {tuss_code}\nInsurer: {insurer_name} (ANS: {insurer_ans_code})\n"
            "Guide: {guide_type}\nCID-10: {cid10_codes}\nReturn JSON only."
        ),
    )


def _make_config(schema_name, glosa_enabled=True):
    """Return a mock TenantAIConfig-like object."""
    cfg = MagicMock()
    cfg.ai_glosa_prediction_enabled = glosa_enabled
    cfg.ai_tuss_enabled = True
    cfg.rate_limit_per_hour = 500
    cfg.monthly_token_ceiling = 500_000
    return cfg


def _claude_glosa_response(risk_level="low", risk_reason="Sem glosa esperada.", risk_code=""):
    payload = json.dumps({
        "risk_level": risk_level,
        "risk_reason": risk_reason,
        "risk_code": risk_code,
    })
    return payload, 50, 30


class PredictGlosaTest(TenantTestCase):

    def setUp(self):
        cache.clear()
        self._override = override_settings(
            ANTHROPIC_API_KEY="test-key",
            FEATURE_AI_GLOSA=True,
            AI_RATE_LIMIT_PER_HOUR=1000,
        )
        self._override.enable()
        self.template = _make_glosa_template()
        self.schema = self.tenant.schema_name

    def tearDown(self):
        self._override.disable()

    def _call(self, **kwargs):
        defaults = dict(
            tuss_code="40302477",
            insurer_ans_code="123456",
            insurer_name="Unimed Nacional",
            cid10_codes=["J18.9"],
            guide_type="sadt",
            schema_name=self.schema,
        )
        defaults.update(kwargs)
        return predict_glosa(**defaults)

    @patch("apps.ai.services.get_tenant_ai_config")
    @patch("apps.ai.services.ClaudeGateway")
    def test_happy_path_returns_prediction(self, MockGateway, mock_config):
        mock_config.return_value = _make_config(self.schema)
        gw = MockGateway.return_value
        gw.complete.return_value = _claude_glosa_response("medium", "Autorização prévia necessária.", "02")

        result = self._call()

        self.assertEqual(result.risk_level, "medium")
        self.assertEqual(result.risk_reason, "Autorização prévia necessária.")
        self.assertEqual(result.risk_code, "02")
        self.assertFalse(result.degraded)
        self.assertFalse(result.cached)
        self.assertIsNotNone(getattr(result, "prediction_id", None))

        # GlosaPrediction row must be created
        pred = GlosaPrediction.objects.get(id=result.prediction_id)
        self.assertEqual(pred.tuss_code, "40302477")
        self.assertEqual(pred.risk_level, "medium")
        self.assertIsNone(pred.guide)
        self.assertIsNone(pred.was_denied)

    @patch("apps.ai.services.get_tenant_ai_config")
    @patch("apps.ai.services.ClaudeGateway")
    def test_cache_hit_skips_llm(self, MockGateway, mock_config):
        mock_config.return_value = _make_config(self.schema)
        gw = MockGateway.return_value
        gw.complete.return_value = _claude_glosa_response("low", "Procedimento frequente.", "")

        # First call populates cache
        self._call()
        first_call_count = gw.complete.call_count

        # Second identical call should hit cache
        result2 = self._call()
        self.assertTrue(result2.cached)
        self.assertEqual(gw.complete.call_count, first_call_count)  # no extra LLM call

    @override_settings(FEATURE_AI_GLOSA=False)
    @patch("apps.ai.services.get_tenant_ai_config")
    def test_global_kill_switch_returns_degraded(self, mock_config):
        mock_config.return_value = _make_config(self.schema)
        result = self._call()
        self.assertTrue(result.degraded)
        self.assertEqual(result.risk_level, "low")
        self.assertEqual(GlosaPrediction.objects.count(), 0)

    @patch("apps.ai.services.get_tenant_ai_config")
    def test_missing_template_returns_degraded(self, mock_config):
        mock_config.return_value = _make_config(self.schema)
        self.template.delete()

        result = self._call()
        self.assertTrue(result.degraded)

    @patch("apps.ai.services.get_tenant_ai_config")
    @patch("apps.ai.services.ClaudeGateway")
    def test_circuit_breaker_isolation_from_tuss(self, MockGateway, mock_config):
        """Glosa circuit should use feature='glosa', independent of 'tuss' circuit."""
        from apps.ai import circuit_breaker
        mock_config.return_value = _make_config(self.schema)
        gw = MockGateway.return_value
        gw.complete.return_value = _claude_glosa_response("low", "OK", "")

        # Trip the TUSS circuit
        for _ in range(circuit_breaker.TRIP_THRESHOLD):
            circuit_breaker.record_failure(self.schema, feature="tuss")
        self.assertTrue(circuit_breaker.is_open(self.schema, feature="tuss"))

        # Glosa circuit must still be closed — prediction succeeds
        result = self._call()
        self.assertFalse(result.degraded)

    @patch("apps.ai.services.get_tenant_ai_config")
    @patch("apps.ai.services.ClaudeGateway")
    def test_prompt_injection_newlines_stripped(self, MockGateway, mock_config):
        """Newlines and braces in insurer_name must be sanitized before prompt."""
        mock_config.return_value = _make_config(self.schema)
        gw = MockGateway.return_value
        gw.complete.return_value = _claude_glosa_response()

        self._call(insurer_name="Insurer\nMalicious{injection}")
        call_args = gw.complete.call_args
        user_prompt = call_args[1].get("user", call_args[0][1] if call_args[0] else "")
        self.assertNotIn("\n", user_prompt.split("Insurer")[1][:30] if "Insurer" in user_prompt else "")
        self.assertNotIn("{", user_prompt)

    @patch("apps.ai.services.get_tenant_ai_config")
    @patch("apps.ai.services.ClaudeGateway")
    def test_invalid_cid10_chars_stripped(self, MockGateway, mock_config):
        """Non-alphanumeric chars in CID-10 codes must be stripped."""
        mock_config.return_value = _make_config(self.schema)
        gw = MockGateway.return_value
        gw.complete.return_value = _claude_glosa_response()

        self._call(cid10_codes=["J18.9; DROP TABLE", "A00"])
        # If we get here without exception, sanitization ran. GlosaPrediction should be created.
        self.assertEqual(GlosaPrediction.objects.count(), 1)
        pred = GlosaPrediction.objects.first()
        # Sanitized codes: alphanumeric only — "J189DROPTABLEmasked" won't appear as-is
        for code in pred.cid10_codes:
            self.assertNotIn(";", code)
            self.assertNotIn(" ", code)
