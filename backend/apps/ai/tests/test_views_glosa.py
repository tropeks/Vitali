"""
Tests for GlosaPredictView (POST /api/v1/ai/glosa-predict/).
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.ai.services import PredictionResult
from apps.core.models import FeatureFlag, Role, User
from apps.test_utils import TenantTestCase

GLOSA_URL = "/api/v1/ai/glosa-predict/"

VALID_PAYLOAD = {
    "tuss_code": "40302477",
    "insurer_ans_code": "123456",
    "insurer_name": "Unimed Nacional",
    "cid10_codes": ["J18.9"],
    "guide_type": "sadt",
}


def _make_user(role_name="faturista"):
    role, _ = Role.objects.get_or_create(
        name=role_name,
        defaults={
            "permissions": ["billing.read", "billing.write", "billing.full", "ai.use", "users.read"]
        },
    )
    return User.objects.create_user(email=f"glosa_{role_name}@test.com", password="pw", role=role)


def _make_glosa_config(enabled=True):
    cfg = MagicMock()
    cfg.ai_glosa_prediction_enabled = enabled
    cfg.ai_tuss_enabled = True
    cfg.rate_limit_per_hour = 500
    cfg.monthly_token_ceiling = 500_000
    return cfg


def _ok_result(**kwargs):
    import uuid

    result = PredictionResult(
        risk_level="low",
        risk_reason="Sem glosa esperada.",
        risk_code="",
        degraded=False,
        cached=False,
    )
    result.prediction_id = uuid.uuid4()
    defaults = {
        "risk_level": "low",
        "risk_reason": "Sem glosa esperada.",
        "risk_code": "",
        "degraded": False,
        "cached": False,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(result, k, v)
    return result


class GlosaPredictViewTest(TenantTestCase):
    def setUp(self):
        cache.clear()
        self._override = override_settings(
            FEATURE_AI_GLOSA=True,
            ANTHROPIC_API_KEY="test-key",
            AI_RATE_LIMIT_PER_HOUR=1000,
        )
        self._override.enable()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="ai_tuss", defaults={"is_enabled": True}
        )
        self.user = _make_user()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        self._override.disable()

    @patch("apps.ai.views.services.get_tenant_ai_config")
    @patch("apps.ai.views.services.predict_glosa")
    def test_returns_200_with_prediction(self, mock_predict, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=True)
        mock_predict.return_value = _ok_result(
            risk_level="medium", risk_reason="Precisa de autorização."
        )

        resp = self.client.post(GLOSA_URL, VALID_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["risk_level"], "medium")
        self.assertFalse(resp.data["degraded"])
        self.assertIn("prediction_id", resp.data)

    @patch("apps.ai.views.services.get_tenant_ai_config")
    def test_returns_200_degraded_when_tenant_disabled(self, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=False)

        resp = self.client.post(GLOSA_URL, VALID_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["degraded"])
        self.assertEqual(resp.data["risk_level"], "low")

    @override_settings(FEATURE_AI_GLOSA=False)
    def test_returns_200_degraded_when_global_kill_switch_off(self):
        resp = self.client.post(GLOSA_URL, VALID_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["degraded"])

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.post(GLOSA_URL, VALID_PAYLOAD, format="json")
        self.assertIn(resp.status_code, [401, 403])

    @patch("apps.ai.views.services.get_tenant_ai_config")
    def test_invalid_ans_code_returns_400(self, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=True)
        bad_payload = {**VALID_PAYLOAD, "insurer_ans_code": "ABC-not-digits"}

        resp = self.client.post(GLOSA_URL, bad_payload, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("insurer_ans_code", resp.data)

    @patch("apps.ai.views.services.get_tenant_ai_config")
    def test_invalid_guide_type_returns_400(self, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=True)
        bad_payload = {**VALID_PAYLOAD, "guide_type": "unknown_type"}

        resp = self.client.post(GLOSA_URL, bad_payload, format="json")

        self.assertEqual(resp.status_code, 400)

    @patch("apps.ai.views.services.get_tenant_ai_config")
    @patch("apps.ai.views.services.predict_glosa")
    def test_degraded_result_still_200(self, mock_predict, mock_config):
        """predict_glosa fails open — degraded=True must still return 200, not 500."""
        mock_config.return_value = _make_glosa_config(enabled=True)
        result = PredictionResult(
            risk_level="low", risk_reason="", risk_code="", degraded=True, cached=False
        )
        result.prediction_id = None
        mock_predict.return_value = result

        resp = self.client.post(GLOSA_URL, VALID_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["degraded"])


GLOSA_BATCH_URL = "/api/v1/ai/glosa-predict-batch/"

VALID_BATCH_PAYLOAD = {
    "insurer_ans_code": "123456",
    "insurer_name": "Unimed Nacional",
    "guide_type": "sadt",
    "items": [
        {"tuss_code": "40302477", "cid10_codes": ["J18.9"]},
        {"tuss_code": "40302485", "cid10_codes": ["J18.9", "B34.9"]},
        {"tuss_code": "40302493", "cid10_codes": []},
    ],
}


class GlosaPredictBatchViewTest(TenantTestCase):
    def setUp(self):
        cache.clear()
        self._override = override_settings(
            FEATURE_AI_GLOSA=True,
            ANTHROPIC_API_KEY="test-key",
            AI_RATE_LIMIT_PER_HOUR=1000,
        )
        self._override.enable()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="ai_tuss", defaults={"is_enabled": True}
        )
        self.user = _make_user("faturista_batch")
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        self._override.disable()

    @patch("apps.ai.views.services.get_tenant_ai_config")
    @patch("apps.ai.views.services.predict_glosa")
    def test_returns_one_prediction_per_item(self, mock_predict, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=True)
        mock_predict.side_effect = [
            _ok_result(risk_level="low", risk_reason="ok"),
            _ok_result(risk_level="medium", risk_reason="Precisa de autorização."),
            _ok_result(risk_level="high", risk_reason="Sem CID-10 vinculado.", degraded=False),
        ]

        resp = self.client.post(GLOSA_BATCH_URL, VALID_BATCH_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["predictions"]), 3)
        self.assertEqual(resp.data["predictions"][0]["tuss_code"], "40302477")
        self.assertEqual(resp.data["predictions"][0]["risk_level"], "low")
        self.assertEqual(resp.data["predictions"][1]["risk_level"], "medium")
        self.assertEqual(resp.data["predictions"][2]["risk_level"], "high")
        self.assertFalse(resp.data["degraded_overall"])
        # Shared insurer + guide_type forwarded to every per-row call
        self.assertEqual(mock_predict.call_count, 3)
        for call in mock_predict.call_args_list:
            self.assertEqual(call.kwargs["insurer_ans_code"], "123456")
            self.assertEqual(call.kwargs["guide_type"], "sadt")

    @patch("apps.ai.views.services.get_tenant_ai_config")
    @patch("apps.ai.views.services.predict_glosa")
    def test_degraded_overall_true_when_any_item_degraded(self, mock_predict, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=True)
        mock_predict.side_effect = [
            _ok_result(risk_level="low"),
            _ok_result(risk_level="low", degraded=True),
            _ok_result(risk_level="low"),
        ]

        resp = self.client.post(GLOSA_BATCH_URL, VALID_BATCH_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["degraded_overall"])

    @patch("apps.ai.views.services.get_tenant_ai_config")
    def test_returns_200_degraded_when_tenant_disabled(self, mock_config):
        mock_config.return_value = _make_glosa_config(enabled=False)

        resp = self.client.post(GLOSA_BATCH_URL, VALID_BATCH_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["degraded_overall"])
        self.assertEqual(len(resp.data["predictions"]), 3)
        for prediction in resp.data["predictions"]:
            self.assertTrue(prediction["degraded"])
            self.assertEqual(prediction["risk_level"], "low")

    @override_settings(FEATURE_AI_GLOSA=False)
    def test_returns_200_degraded_when_global_kill_switch_off(self):
        resp = self.client.post(GLOSA_BATCH_URL, VALID_BATCH_PAYLOAD, format="json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["degraded_overall"])
        self.assertEqual(len(resp.data["predictions"]), 3)

    def test_empty_items_returns_400(self):
        payload = {**VALID_BATCH_PAYLOAD, "items": []}
        resp = self.client.post(GLOSA_BATCH_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_guide_type_returns_400(self):
        payload = {**VALID_BATCH_PAYLOAD, "guide_type": "unknown_type"}
        resp = self.client.post(GLOSA_BATCH_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.post(GLOSA_BATCH_URL, VALID_BATCH_PAYLOAD, format="json")
        self.assertIn(resp.status_code, [401, 403])
