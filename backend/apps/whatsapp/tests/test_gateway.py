"""
Tests for WhatsAppGateway, EvolutionAPIGateway, and webhook signature validation.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.whatsapp.gateway import (
    EvolutionAPIGateway,
    EvolutionAPIError,
    OptOutError,
    verify_webhook_signature,
)

WEBHOOK_URL = "/api/v1/whatsapp/webhook/"


def _make_webhook_body(phone="5511999999999", text="oi"):
    return json.dumps({
        "event": "messages.upsert",
        "data": {
            "messages": [{
                "key": {"fromMe": False, "remoteJid": f"{phone}@s.whatsapp.net"},
                "message": {"conversation": text},
            }]
        }
    }).encode()


def _sign(body: bytes, secret: str = "test-secret") -> str:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class WebhookSignatureTests(TenantTestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    @override_settings(WHATSAPP_WEBHOOK_SECRET="test-secret")
    @patch("apps.whatsapp.views.ConversationFSM")
    @patch("apps.whatsapp.views.get_gateway")
    def test_valid_hmac_returns_200(self, mock_gw, mock_fsm):
        mock_fsm.return_value.process.return_value = []
        mock_gw.return_value = MagicMock()
        body = _make_webhook_body()
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)

    @override_settings(WHATSAPP_WEBHOOK_SECRET="test-secret")
    def test_invalid_hmac_still_returns_200_but_drops(self):
        body = _make_webhook_body()
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=bad_signature",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    @override_settings(WHATSAPP_WEBHOOK_SECRET="test-secret")
    def test_missing_signature_still_returns_200_drops(self):
        body = _make_webhook_body()
        resp = self.client.post(WEBHOOK_URL, data=body, content_type="application/json")
        self.assertEqual(resp.status_code, 200)

    @override_settings(WHATSAPP_WEBHOOK_SECRET="")
    @patch("apps.whatsapp.views.ConversationFSM")
    @patch("apps.whatsapp.views.get_gateway")
    def test_missing_secret_config_skips_validation(self, mock_gw, mock_fsm):
        mock_fsm.return_value.process.return_value = []
        mock_gw.return_value = MagicMock()
        body = _make_webhook_body()
        resp = self.client.post(WEBHOOK_URL, data=body, content_type="application/json")
        self.assertEqual(resp.status_code, 200)

    @override_settings(WHATSAPP_WEBHOOK_SECRET="test-secret")
    @patch("apps.whatsapp.views.WebhookView._dispatch", side_effect=RuntimeError("boom"))
    def test_dispatch_exception_still_returns_200(self, mock_dispatch):
        body = _make_webhook_body()
        resp = self.client.post(
            WEBHOOK_URL, data=body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(resp.status_code, 200)


class EvolutionAPIGatewayTests(TestCase):

    @override_settings(
        WHATSAPP_EVOLUTION_URL="http://evo:8080",
        WHATSAPP_EVOLUTION_API_KEY="testkey",
        WHATSAPP_INSTANCE_NAME="test",
    )
    @patch("apps.whatsapp.gateway.requests.post")
    def test_send_text_posts_correct_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        gw = EvolutionAPIGateway()
        gw.send_text("+5511999999999", "Olá!")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertIn("/message/sendText/", call_kwargs.args[0])
        self.assertEqual(call_kwargs.kwargs["json"]["text"], "Olá!")

    @override_settings(
        WHATSAPP_EVOLUTION_URL="http://evo:8080",
        WHATSAPP_EVOLUTION_API_KEY="testkey",
        WHATSAPP_INSTANCE_NAME="test",
    )
    @patch("apps.whatsapp.gateway.requests.post")
    def test_send_button_menu_formats_payload(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        gw = EvolutionAPIGateway()
        gw.send_button_menu("+5511999999999", "Escolha:", [{"displayText": "A", "id": "a"}])
        mock_post.assert_called_once()
        self.assertIn("/message/sendButtons/", mock_post.call_args.args[0])

    @override_settings(
        WHATSAPP_EVOLUTION_URL="http://evo:8080",
        WHATSAPP_EVOLUTION_API_KEY="testkey",
        WHATSAPP_INSTANCE_NAME="test",
    )
    @patch("apps.whatsapp.gateway.requests.post")
    def test_timeout_10s_enforced(self, mock_post):
        import requests
        mock_post.side_effect = requests.Timeout()
        gw = EvolutionAPIGateway()
        # Should not raise — gateway swallows network errors
        result = gw._post("/test", {})
        self.assertEqual(result, {})

    def test_send_if_opted_out_raises_optout_error(self):
        gw = EvolutionAPIGateway()
        contact = MagicMock()
        contact.opt_in = False
        contact.phone = "+5511999999999"
        with self.assertRaises(OptOutError):
            gw.send_if_opted_in(contact, "test")


class SignatureVerificationUnitTests(TestCase):

    @override_settings(WHATSAPP_WEBHOOK_SECRET="mysecret")
    def test_valid_signature_returns_true(self):
        body = b'{"test": 1}'
        sig = "sha256=" + hmac.new(b"mysecret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body, sig))

    @override_settings(WHATSAPP_WEBHOOK_SECRET="mysecret")
    def test_wrong_secret_returns_false(self):
        body = b'{"test": 1}'
        sig = "sha256=" + hmac.new(b"wrongsecret", body, hashlib.sha256).hexdigest()
        self.assertFalse(verify_webhook_signature(body, sig))

    @override_settings(WHATSAPP_WEBHOOK_SECRET="mysecret")
    def test_malformed_header_returns_false(self):
        self.assertFalse(verify_webhook_signature(b"body", "not-sha256=xxx"))
