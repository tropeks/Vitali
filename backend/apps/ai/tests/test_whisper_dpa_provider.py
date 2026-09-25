"""
Ordem 024 — o Whisper sai do caminho até constar no DPA.

The DPA a clinic signs (frontend/components/settings/DPASignModal.tsx, §2
"Suboperador") names only Anthropic, PBC. Consent used to be checked per
FEATURE, so the same signed AIDPAStatus that authorizes Anthropic also let the
consultation audio (voice is biometric data, LGPD art. 5º II) go to OpenAI.
The gate now checks the PROVIDER against the suboperators the DPA covers.
"""

import datetime
import os
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.ai.consent import requires_ai_consent
from apps.core.models import AIDPAStatus
from apps.emr.services.whisper import WhisperConsentError, WhisperGateway
from apps.test_utils import TenantTestCase


class WhisperFlagDefaultTest(SimpleTestCase):
    def test_whisper_fallback_is_off_by_default(self):
        self.assertNotIn(
            "FEATURE_WHISPER_FALLBACK",
            os.environ,
            "o ambiente de teste define FEATURE_WHISPER_FALLBACK; o default não é testável aqui",
        )
        self.assertIs(settings.FEATURE_WHISPER_FALLBACK, False)


class WhisperProviderNotInDPATest(TenantTestCase):
    def setUp(self):
        self.schema = self.tenant.schema_name
        AIDPAStatus.objects.using("default").update_or_create(
            tenant=self.tenant, defaults={"dpa_signed_date": datetime.date.today()}
        )

    @override_settings(FEATURE_WHISPER_FALLBACK=True)
    def test_signed_dpa_does_not_cover_openai(self):
        result = requires_ai_consent("whisper", self.schema)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "provider_not_in_dpa")

    @override_settings(FEATURE_WHISPER_FALLBACK=False)
    def test_provider_check_comes_before_every_other_gate(self):
        """The provider refusal must not depend on any setting or row."""
        with patch("apps.ai.consent._dpa_signed") as dpa_lookup:
            result = requires_ai_consent("whisper", self.schema)
        self.assertEqual(result.reason, "provider_not_in_dpa")
        dpa_lookup.assert_not_called()

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=True, OPENAI_API_KEY="k")
    def test_gateway_never_reaches_openai_with_a_signed_dpa(self):
        with patch("openai.OpenAI") as openai_client:
            # If the gate lets the call through, a transcription comes back and
            # the test fails on the assertion below, not on a MagicMock.
            openai_client.return_value.audio.transcriptions.create.return_value.text = "x"
            with self.assertRaises(WhisperConsentError) as ctx:
                WhisperGateway().transcribe(b"fake-audio", "audio/webm", tenant_schema=self.schema)
        openai_client.assert_not_called()
        self.assertEqual(ctx.exception.reason, "provider_not_in_dpa")

    @override_settings(FEATURE_AI_SCRIBE=True)
    def test_anthropic_features_are_unaffected(self):
        self.assertTrue(requires_ai_consent("scribe", self.schema).allowed)
