"""
Tests for S-073 Whisper API Transcription Fallback.

Tests:
  - Feature flag FEATURE_WHISPER_FALLBACK OFF → 404
  - Feature flag FEATURE_AI_SCRIBE OFF → 404
  - DPA not signed → 403
  - Valid multipart audio upload → WhisperGateway called, transcription returned
  - File larger than 25 MB → 400
  - Invalid content type (not audio/*) → 400
  - WhisperGateway raises WhisperError → 503
"""

import io
from unittest.mock import MagicMock, patch

from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.test_utils import TenantTestCase


def _make_audio_file(size_bytes: int = 1024, content_type: str = "audio/webm") -> io.BytesIO:
    """Return a BytesIO suitable for APIClient multipart audio uploads.

    `content_type` is accepted for callsite readability but APIClient determines
    the multipart Content-Type automatically — only the byte payload is used.
    """
    del content_type  # signature kept for caller clarity; APIClient sets Content-Type
    return io.BytesIO(b"x" * size_bytes)


class TestScribeTranscribeView(TenantTestCase):
    def setUp(self):
        import datetime

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from apps.emr.models import Encounter, Patient, Professional

        User = get_user_model()
        self.user = User.objects.create_user(
            email="whisper_test@clinic.test",
            password="TestPass123!",
            full_name="Whisper Doctor",
        )
        self.patient = Patient.objects.create(
            full_name="Whisper Patient",
            cpf="111.222.333-44",
            birth_date=datetime.date(1985, 6, 15),
            gender="F",
        )
        self.professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="777888",
            council_state="SP",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient,
            professional=self.professional,
            encounter_date=timezone.now(),
        )

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

        self.url = f"/api/v1/encounters/{self.encounter.pk}/scribe/transcribe/"

    def _post_audio(self, size_bytes: int = 1024, content_type: str = "audio/webm"):
        audio = _make_audio_file(size_bytes)
        return self.client.post(
            self.url,
            data={"audio": audio},
            format="multipart",
            CONTENT_TYPE_OVERRIDE=content_type,  # multipart auto-set by APIClient
        )

    # ── Feature flag checks ───────────────────────────────────────────────────

    @override_settings(FEATURE_WHISPER_FALLBACK=False, FEATURE_AI_SCRIBE=True)
    def test_whisper_fallback_flag_off_returns_404(self):
        """FEATURE_WHISPER_FALLBACK=False → 404."""
        audio = io.BytesIO(b"x" * 512)
        res = self.client.post(self.url, data={"audio": audio}, format="multipart")
        self.assertEqual(res.status_code, 404)

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=False)
    def test_scribe_flag_off_returns_404(self):
        """FEATURE_AI_SCRIBE=False → 404."""
        audio = io.BytesIO(b"x" * 512)
        res = self.client.post(self.url, data={"audio": audio}, format="multipart")
        self.assertEqual(res.status_code, 404)

    # ── DPA check ─────────────────────────────────────────────────────────────

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=True)
    def test_dpa_not_signed_returns_403(self):
        """DPA not signed → 403."""
        with patch("apps.emr.views_scribe._check_dpa_signed", return_value=False):
            audio = io.BytesIO(b"x" * 512)
            res = self.client.post(self.url, data={"audio": audio}, format="multipart")
        self.assertEqual(res.status_code, 403)

    # ── Validation checks ─────────────────────────────────────────────────────

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    def test_file_too_large_returns_400(self, _mock_dpa):
        """Audio file > 25 MB → 400."""
        large_audio = io.BytesIO(b"x" * (25 * 1024 * 1024 + 1))
        large_audio.name = "audio.webm"
        # Manually set size attribute so DRF InMemoryUploadedFile.size is correct
        large_audio.size = 25 * 1024 * 1024 + 1

        from django.core.files.uploadedfile import InMemoryUploadedFile

        uploaded = InMemoryUploadedFile(
            file=large_audio,
            field_name="audio",
            name="audio.webm",
            content_type="audio/webm",
            size=25 * 1024 * 1024 + 1,
            charset=None,
        )
        res = self.client.post(self.url, data={"audio": uploaded}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("grande", res.json()["detail"].lower())

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    def test_invalid_content_type_returns_400(self, _mock_dpa):
        """Non-audio content type → 400."""
        from django.core.files.uploadedfile import InMemoryUploadedFile

        fake_pdf = InMemoryUploadedFile(
            file=io.BytesIO(b"%PDF fake"),
            field_name="audio",
            name="file.pdf",
            content_type="application/pdf",
            size=9,
            charset=None,
        )
        res = self.client.post(self.url, data={"audio": fake_pdf}, format="multipart")
        self.assertEqual(res.status_code, 400)

    # ── Happy path ────────────────────────────────────────────────────────────

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    @patch("apps.emr.views_scribe.WhisperGateway")
    def test_valid_audio_returns_transcription(self, MockWhisperGateway, _mock_dpa):
        """Valid audio upload → WhisperGateway.transcribe called, transcription returned."""
        mock_gw_instance = MagicMock()
        mock_gw_instance.transcribe.return_value = "Paciente relata dor de cabeça há dois dias."
        MockWhisperGateway.return_value = mock_gw_instance

        from django.core.files.uploadedfile import InMemoryUploadedFile

        audio_bytes = b"fake_audio_data"
        uploaded = InMemoryUploadedFile(
            file=io.BytesIO(audio_bytes),
            field_name="audio",
            name="audio.webm",
            content_type="audio/webm",
            size=len(audio_bytes),
            charset=None,
        )

        res = self.client.post(self.url, data={"audio": uploaded}, format="multipart")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("transcription", data)
        self.assertEqual(data["transcription"], "Paciente relata dor de cabeça há dois dias.")
        mock_gw_instance.transcribe.assert_called_once()
        call_args = mock_gw_instance.transcribe.call_args
        self.assertEqual(call_args[0][0], audio_bytes)
        self.assertEqual(call_args[0][1], "audio/webm")

    # ── Service error ─────────────────────────────────────────────────────────

    @override_settings(FEATURE_WHISPER_FALLBACK=True, FEATURE_AI_SCRIBE=True)
    @patch("apps.emr.views_scribe._check_dpa_signed", return_value=True)
    @patch("apps.emr.views_scribe.WhisperGateway")
    def test_whisper_error_returns_503(self, MockWhisperGateway, _mock_dpa):
        """WhisperGateway.transcribe raises WhisperError → 503."""
        from apps.emr.services.whisper import WhisperError

        mock_gw_instance = MagicMock()
        mock_gw_instance.transcribe.side_effect = WhisperError("API quota exceeded")
        MockWhisperGateway.return_value = mock_gw_instance

        from django.core.files.uploadedfile import InMemoryUploadedFile

        uploaded = InMemoryUploadedFile(
            file=io.BytesIO(b"audio"),
            field_name="audio",
            name="audio.webm",
            content_type="audio/webm",
            size=5,
            charset=None,
        )

        res = self.client.post(self.url, data={"audio": uploaded}, format="multipart")
        self.assertEqual(res.status_code, 503)
