"""
S-069: AI Clinical Scribe endpoints.

POST /encounters/{id}/scribe/start/      — create AIScribeSession and dispatch async SOAP generation
GET  /encounters/{id}/scribe/status/     — return latest session status for encounter
POST /encounters/{id}/scribe/transcribe/ — S-073: server-side Whisper audio transcription fallback
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Encounter
from .services.whisper import WhisperError, WhisperGateway

MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB

logger = logging.getLogger(__name__)


def _check_dpa_signed(schema_name: str) -> bool:
    """Reuse the DPA check pattern from prescription_safety."""
    try:
        from apps.core.models import AIDPAStatus, Tenant

        tenant = Tenant.objects.get(schema_name=schema_name)
        try:
            dpa = tenant.ai_dpa_status
            return dpa.is_signed
        except AIDPAStatus.DoesNotExist:
            return False
    except Exception:
        logger.warning("views_scribe: could not check DPA for schema %s", schema_name)
        return False


class ScribeStartView(APIView):
    """
    POST /encounters/{encounter_id}/scribe/start/
    Body: { "transcription": "..." }
    Returns: { "session_id": "...", "status": "processing" }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, encounter_id):
        if not getattr(settings, "FEATURE_AI_SCRIBE", False):
            return Response(
                {"detail": "AI Scribe feature is not enabled."},
                status=status.HTTP_404_NOT_FOUND,
            )

        schema_name = request.tenant.schema_name
        if not _check_dpa_signed(schema_name):
            return Response(
                {
                    "detail": "DPA não assinado. O uso de IA requer assinatura do DPA de dados de saúde."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        transcription = (request.data.get("transcription") or "").strip()
        if not transcription:
            return Response(
                {"detail": "transcription é obrigatório e não pode estar vazio."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(transcription) > 10_000:
            return Response(
                {"detail": "Transcrição muito longa (máx 10.000 caracteres)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            encounter = Encounter.objects.get(pk=encounter_id)
        except Encounter.DoesNotExist:
            return Response(
                {"detail": "Consulta não encontrada."}, status=status.HTTP_404_NOT_FOUND
            )

        if encounter.status != "open":
            return Response(
                {"detail": "Transcrição só pode ser adicionada a consultas abertas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.ai.models import AIScribeSession
        from apps.ai.tasks import generate_soap_task

        session = AIScribeSession.objects.create(
            encounter=encounter,
            raw_transcription=transcription,
        )

        generate_soap_task.delay(str(session.id))

        return Response(
            {"session_id": str(session.id), "status": session.status},
            status=status.HTTP_202_ACCEPTED,
        )


class ScribeStatusView(APIView):
    """
    GET /encounters/{encounter_id}/scribe/status/
    Returns the latest AIScribeSession for the encounter.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, encounter_id):
        try:
            Encounter.objects.get(pk=encounter_id)
        except Encounter.DoesNotExist:
            return Response(
                {"detail": "Consulta não encontrada."}, status=status.HTTP_404_NOT_FOUND
            )

        from apps.ai.models import AIScribeSession

        session = AIScribeSession.objects.filter(encounter_id=encounter_id).first()
        if not session:
            return Response({"status": "none"})

        data = {
            "session_id": str(session.id),
            "status": session.status,
            "created_at": session.created_at.isoformat(),
        }
        if session.status == AIScribeSession.Status.COMPLETED:
            data["soap"] = session.soap_json
        elif session.status == AIScribeSession.Status.FAILED:
            data["error"] = session.error_message

        return Response(data)


class ScribeTranscribeView(APIView):
    """
    S-073: POST /encounters/{encounter_id}/scribe/transcribe/

    Accepts multipart/form-data with an `audio` file field.
    Proxies audio to the OpenAI Whisper API and returns the transcription text.
    Used as a fallback for browsers that do not support the Web Speech API.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request, encounter_id):
        if not getattr(settings, "FEATURE_WHISPER_FALLBACK", False):
            return Response(
                {"detail": "Funcionalidade de transcrição por áudio não está habilitada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not getattr(settings, "FEATURE_AI_SCRIBE", False):
            return Response(
                {"detail": "AI Scribe feature is not enabled."},
                status=status.HTTP_404_NOT_FOUND,
            )

        schema_name = request.tenant.schema_name
        if not _check_dpa_signed(schema_name):
            return Response(
                {
                    "detail": "DPA não assinado. O uso de IA requer assinatura do DPA de dados de saúde."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        audio_file = request.FILES.get("audio")
        if not audio_file:
            return Response(
                {"detail": "Campo 'audio' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = audio_file.content_type or ""
        if not content_type.startswith("audio/"):
            return Response(
                {"detail": "Tipo de arquivo inválido. Apenas arquivos de áudio são aceitos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if audio_file.size > MAX_AUDIO_SIZE:
            return Response(
                {"detail": "Arquivo de áudio muito grande. O tamanho máximo é 25 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        audio_bytes = audio_file.read()

        try:
            transcription = WhisperGateway().transcribe(audio_bytes, content_type)
        except WhisperError as exc:
            logger.error("views_scribe: WhisperError for encounter %s: %s", encounter_id, exc)
            return Response(
                {"detail": "Serviço de transcrição indisponível. Tente novamente mais tarde."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"transcription": transcription})
