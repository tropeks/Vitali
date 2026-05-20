"""Tests for ClaudeGateway."""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.ai.gateway import ClaudeGateway, LLMGatewayError, reset_anthropic_client_cache


@override_settings(ANTHROPIC_API_KEY="test-key", AI_SUGGEST_TIMEOUT_S=5)
class ClaudeGatewayTest(TestCase):
    def setUp(self):
        # Each test starts with a clean client cache so reuse assertions are
        # decoupled from earlier tests.
        reset_anthropic_client_cache()

    def tearDown(self):
        reset_anthropic_client_cache()

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

    def test_reuses_anthropic_client_across_gateways_with_same_credentials(self):
        """Same (api_key, timeout) → anthropic.Anthropic() built once and reused."""
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = self._mock_anthropic()
            gw1 = ClaudeGateway()
            gw2 = ClaudeGateway()
            gw1.complete(system="sys", user="usr")
            gw2.complete(system="sys", user="usr")
            gw1.complete(system="sys", user="usr")

        # Anthropic constructor called exactly once despite three calls across
        # two gateway instances — proves the connection pool is reused.
        self.assertEqual(MockClient.call_count, 1)
        # All three calls still landed on the SDK.
        self.assertEqual(MockClient.return_value.messages.create.call_count, 3)

    def test_different_credentials_get_distinct_clients(self):
        """Different api_key (e.g. different tenant overrides) → distinct clients."""
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = self._mock_anthropic()
            ClaudeGateway(api_key="key-a").complete(system="sys", user="usr")
            ClaudeGateway(api_key="key-b").complete(system="sys", user="usr")
            ClaudeGateway(api_key="key-a").complete(system="sys", user="usr")

        # Two distinct keys → two clients; the second 'key-a' reuses the first.
        self.assertEqual(MockClient.call_count, 2)
