"""
Tests for apps.emr.services.whisper.WhisperGateway (Onda 3 / 3.1+3.2).

Lives under apps/ai/tests per the ticket's test-location convention, even
though the gateway itself lives in apps/emr/services (out of this ticket's
touch-scope) — apps.ai -> apps.emr is an already-grandfathered import
direction (see .importlinter), and apps.emr -> apps.ai (the gateway calling
apps.ai.consent/models/phi_scrubber) is grandfathered too.
"""

import datetime
from unittest.mock import MagicMock, patch

from django.test import override_settings

from apps.ai.consent import ConsentResult
from apps.ai.models import AIUsageLog
from apps.core.models import AIDPAStatus
from apps.emr.services.whisper import WhisperConsentError, WhisperError, WhisperGateway
from apps.test_utils import TenantTestCase


def _mock_openai_response(text="Paciente relata febre há dois dias."):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = MagicMock(text=text)
    return mock_client


class WhisperGatewayConsentTest(TenantTestCase):
    def setUp(self):
        self.schema = self.tenant.schema_name

    def test_consent_denied_raises_and_never_calls_openai(self):
        with (
            patch(
                "apps.ai.consent.requires_ai_consent",
                return_value=ConsentResult(False, "dpa_not_signed"),
            ),
            patch("openai.OpenAI") as MockOpenAI,
        ):
            with self.assertRaises(WhisperConsentError):
                WhisperGateway().transcribe(b"fake-audio", "audio/webm", tenant_schema=self.schema)
        MockOpenAI.assert_not_called()

    def test_consent_denied_writes_no_audio_usage_log(self):
        AIUsageLog.objects.all().delete()
        with patch(
            "apps.ai.consent.requires_ai_consent",
            return_value=ConsentResult(False, "feature_disabled_global"),
        ):
            with self.assertRaises(WhisperConsentError):
                WhisperGateway().transcribe(b"fake-audio", "audio/webm", tenant_schema=self.schema)
        # Consent denial happens before any external call — no attempt to log.
        self.assertEqual(AIUsageLog.objects.count(), 0)


@override_settings(FEATURE_WHISPER_FALLBACK=True, OPENAI_API_KEY="test-key")
class WhisperGatewayUsageLogTest(TenantTestCase):
    """Onda 3 / 3.1 audit finding: Whisper made zero AIUsageLog entries before this ticket."""

    def setUp(self):
        self.schema = self.tenant.schema_name
        AIDPAStatus.objects.using("default").update_or_create(
            tenant=self.tenant, defaults={"dpa_signed_date": datetime.date.today()}
        )
        AIUsageLog.objects.all().delete()

    def test_successful_transcription_creates_ai_usage_log(self):
        with patch("openai.OpenAI", return_value=_mock_openai_response()):
            result = WhisperGateway().transcribe(
                b"fake-audio", "audio/webm", tenant_schema=self.schema
            )

        self.assertEqual(result, "Paciente relata febre há dois dias.")
        self.assertEqual(AIUsageLog.objects.count(), 1)
        log = AIUsageLog.objects.get()
        self.assertEqual(log.event_type, "llm_call")
        self.assertEqual(log.model, "whisper-1")

    def test_failed_transcription_still_creates_ai_usage_log(self):
        """Onda 3 / 3.1: 'toda chamada externa' includes failed attempts — the
        audio still reached (or tried to reach) OpenAI with PHI regardless of
        outcome."""
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = Exception("OpenAI 500")

        with patch("openai.OpenAI", return_value=mock_client):
            with self.assertRaises(WhisperError):
                WhisperGateway().transcribe(b"fake-audio", "audio/webm", tenant_schema=self.schema)

        self.assertEqual(AIUsageLog.objects.count(), 1)
        self.assertEqual(AIUsageLog.objects.get().event_type, "degraded")

    def test_returned_transcription_text_is_generic_scrubbed_in_log(self):
        """The gateway has no Patient context, so only the regex sweep runs —
        documented limitation, see whisper.py module docstring."""
        with patch(
            "openai.OpenAI",
            return_value=_mock_openai_response("Contato: paciente@example.com, CPF 123.456.789-00"),
        ):
            WhisperGateway().transcribe(b"fake-audio", "audio/webm", tenant_schema=self.schema)

        log = AIUsageLog.objects.get()
        self.assertNotIn("paciente@example.com", log.input_text)
        self.assertNotIn("123.456.789-00", log.input_text)

    def test_defaults_tenant_schema_from_connection(self):
        """Existing call sites (views_scribe.py) don't pass tenant_schema —
        it must fall back to the current DB connection's schema."""
        with patch("openai.OpenAI", return_value=_mock_openai_response()):
            WhisperGateway().transcribe(b"fake-audio", "audio/webm")

        self.assertEqual(AIUsageLog.objects.count(), 1)
