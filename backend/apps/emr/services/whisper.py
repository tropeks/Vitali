"""
S-073: Whisper API gateway for server-side audio transcription.

LGPD note (Onda 3 / 3.1 audit): the audio uploaded here contains voice
(biometric data, LGPD Art. 5º II) plus whatever the patient/professional say
— name, complaint, diagnosis. Unlike transcript TEXT, this module CANNOT
de-identify the audio itself before it goes to OpenAI: there is no text
substitution possible on a waveform. The only available mitigations are (a)
gating the call on an explicit consent decision (global flag + signed DPA +
monthly ceiling, see apps.ai.consent) and (b) an audit trail of every call —
both implemented below. Do not represent this as de-identification; it isn't.
The TEXT that comes back, however, is scrubbed before it is written to the
audit log (apps.ai.phi_scrubber.scrub_generic — regex-only here, since this
gateway has no Patient context to do directed scrubbing; see transcribe()).
"""

import io
import logging

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)


class WhisperError(Exception):
    """Raised when the Whisper API call fails."""


class WhisperConsentError(WhisperError):
    """Raised when the consent gate (apps.ai.consent) denies the call."""


class WhisperGateway:
    """Gateway for OpenAI Whisper audio transcription."""

    def transcribe(
        self,
        audio_bytes: bytes,
        content_type: str,
        tenant_schema: str | None = None,
    ) -> str:
        """
        Transcribe audio bytes using the OpenAI Whisper API.

        Args:
            audio_bytes: Raw audio data. Sent to OpenAI as-is — see module
                docstring on why this cannot be de-identified.
            content_type: MIME type of the audio (e.g. 'audio/webm').
            tenant_schema: tenant schema to gate/log against. Defaults to the
                current DB connection's schema (correct for both a normal
                request and a tenant-scoped Celery task) so existing callers
                that don't pass it explicitly still get the consent check.

        Returns:
            Transcription text string.

        Raises:
            WhisperConsentError: consent gate denied the call (feature
                disabled, DPA not signed, or monthly ceiling exceeded).
            WhisperError: the OpenAI API call itself failed.
        """
        from apps.ai.consent import requires_ai_consent
        from apps.ai.phi_scrubber import scrub_generic

        schema_name: str = tenant_schema or str(getattr(connection, "schema_name", "public"))

        consent = requires_ai_consent("whisper", schema_name)
        if not consent.allowed:
            logger.warning(
                "WhisperGateway: consent denied (%s) for tenant=%s", consent.reason, schema_name
            )
            raise WhisperConsentError(f"AI consent denied: {consent.reason}")

        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise WhisperError("openai package not installed") from exc

        # Determine file extension from content type for the Whisper API filename hint
        ext_map = {
            "audio/webm": "webm",
            "audio/ogg": "ogg",
            "audio/mp4": "mp4",
            "audio/mpeg": "mp3",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/flac": "flac",
            "audio/m4a": "m4a",
        }
        # Strip codec params (e.g. "audio/webm;codecs=opus" -> "audio/webm")
        base_type = content_type.split(";")[0].strip().lower()
        ext = ext_map.get(base_type, "webm")
        filename = f"audio.{ext}"

        try:
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            file_tuple = (filename, io.BytesIO(audio_bytes), content_type)
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=file_tuple,
                language="pt",
            )
            transcription = response.text
        except Exception as exc:
            # Onda 3 / 3.1: every external call gets an audit trail, failures
            # included — this attempt reached OpenAI (or tried to) with PHI
            # audio regardless of the outcome.
            self._log_usage(event_type="degraded", model="whisper-1")
            raise WhisperError(str(exc)) from exc

        # AIUsageLog.input_text is encrypted at rest (apps.ai.models). It is
        # NOT directed-scrubbed against the Patient — this gateway has no
        # Patient in scope, only tenant_schema — so only the generic
        # regex sweep (CPF/CNS/phone/e-mail/date) runs. A name that isn't
        # formatted as one of those WILL still reach this log verbatim.
        self._log_usage(
            event_type="llm_call",
            model="whisper-1",
            input_text=scrub_generic(transcription),
        )
        return transcription

    @staticmethod
    def _log_usage(event_type: str, model: str, input_text: str = "") -> None:
        from apps.ai.models import AIUsageLog

        try:
            AIUsageLog.objects.create(
                event_type=event_type,
                model=model,
                input_text=input_text[:500],
            )
        except Exception as exc:  # pragma: no cover — audit logging must never break the request
            logger.warning("WhisperGateway: could not write AIUsageLog: %s", exc)
