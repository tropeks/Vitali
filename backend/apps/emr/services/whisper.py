"""
S-073: Whisper API gateway for server-side audio transcription.
"""
import io

from django.conf import settings


class WhisperError(Exception):
    """Raised when the Whisper API call fails."""


class WhisperGateway:
    """Gateway for OpenAI Whisper audio transcription."""

    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        """
        Transcribe audio bytes using the OpenAI Whisper API.

        Args:
            audio_bytes: Raw audio data.
            content_type: MIME type of the audio (e.g. 'audio/webm').

        Returns:
            Transcription text string.

        Raises:
            WhisperError: If the API call fails.
        """
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
            return response.text
        except Exception as exc:
            raise WhisperError(str(exc)) from exc
