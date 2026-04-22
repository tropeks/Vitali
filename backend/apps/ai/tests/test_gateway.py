"""Tests for ClaudeGateway."""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.ai.gateway import ClaudeGateway, LLMGatewayError


@override_settings(ANTHROPIC_API_KEY="test-key", AI_SUGGEST_TIMEOUT_S=5)
class ClaudeGatewayTest(TestCase):
    def _mock_anthropic(self, text="test response"):
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=text)]
        mock_msg.usage.input_tokens = 50
        mock_msg.usage.output_tokens = 20
        return mock_msg

    def test_returns_text_and_token_counts(self):
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = self._mock_anthropic(
                '{"suggestions": []}'
            )
            gw = ClaudeGateway()
            text, tokens_in, tokens_out = gw.complete(system="sys", user="usr")

        self.assertEqual(text, '{"suggestions": []}')
        self.assertEqual(tokens_in, 50)
        self.assertEqual(tokens_out, 20)

    def test_passes_haiku_model(self):
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = self._mock_anthropic()
            gw = ClaudeGateway()
            gw.complete(system="sys", user="usr")
            call_kwargs = MockClient.return_value.messages.create.call_args[1]

        self.assertEqual(call_kwargs["model"], "claude-haiku-4-5-20251001")

    def test_raises_on_api_error(self):
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = Exception("API 500")
            gw = ClaudeGateway()
            with self.assertRaises(LLMGatewayError):
                gw.complete(system="sys", user="usr")

    def test_raises_without_api_key(self):
        with override_settings(ANTHROPIC_API_KEY=""):
            gw = ClaudeGateway()
            with self.assertRaises(LLMGatewayError):
                gw.complete(system="sys", user="usr")
