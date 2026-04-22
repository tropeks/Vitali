"""
S-064: DRF views for CID-10 AI suggestion.

Endpoints:
  POST /emr/encounters/{id}/cid10-suggest/
       Returns AI-suggested CID-10 codes for free-text diagnosis.

  POST /emr/encounters/{id}/cid10-accept/
       Records acceptance of a suggestion and optionally updates Encounter.
"""

import logging

from django.db import connection
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.emr.models import AICIDSuggestion, Encounter

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 15


class CID10SuggestView(APIView):
    """
    POST /emr/encounters/{encounter_id}/cid10-suggest/

    Body: {text: str}

    Returns AI-suggested CID-10 codes for the given diagnosis text.
    Creates an AICIDSuggestion record for tracking.
    Returns empty suggestions (200 OK) if text is shorter than 15 chars.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, encounter_id):
        try:
            encounter = Encounter.objects.get(id=encounter_id)
        except Encounter.DoesNotExist:
            return Response(
                {"error": "Consulta não encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        text = request.data.get("text", "").strip()

        if len(text) < MIN_TEXT_LENGTH:
            return Response(
                {"suggestions": []},
                status=status.HTTP_200_OK,
            )

        # Import here to avoid circular import
        from apps.ai.services_cid10 import CID10Suggester

        schema_name = connection.schema_name
        suggester = CID10Suggester()
        result = suggester.suggest(text=text, schema_name=schema_name)

        suggestions_data = [
            {
                "code": s.code,
                "description": s.description,
                "confidence": s.confidence,
            }
            for s in result.suggestions
        ]

        # Record the suggestion for tracking (even if degraded/empty)
        suggestion_record = None
        try:
            suggestion_record = AICIDSuggestion.objects.create(
                encounter=encounter,
                query_text=text,
                suggestions=suggestions_data,
            )
        except Exception:
            logger.warning("Failed to create AICIDSuggestion record", exc_info=True)

        response_data = {"suggestions": suggestions_data}
        if suggestion_record:
            response_data["suggestion_id"] = str(suggestion_record.id)
        if result.degraded:
            response_data["degraded"] = True

        return Response(response_data, status=status.HTTP_200_OK)


class CID10AcceptView(APIView):
    """
    POST /emr/encounters/{encounter_id}/cid10-accept/

    Body: {suggestion_id: uuid, code: str}

    Updates AICIDSuggestion.accepted_code.
    If Encounter has a cid10_codes (SOAPNote) or diagnosis_cid10 field, updates it.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, encounter_id):
        try:
            encounter = Encounter.objects.get(id=encounter_id)
        except Encounter.DoesNotExist:
            return Response(
                {"error": "Consulta não encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        suggestion_id = request.data.get("suggestion_id")
        code = request.data.get("code", "").strip().upper()

        if not suggestion_id:
            return Response(
                {"error": "suggestion_id é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not code:
            return Response(
                {"error": "code é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate code exists in CID10Code table (anti-hallucination)
        try:
            from apps.core.models import CID10Code

            if not CID10Code.objects.using("public").filter(code=code, active=True).exists():
                return Response(
                    {"error": f"Código CID-10 inválido ou inativo: {code}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception:
            logger.warning("Could not validate CID10 code %s", code, exc_info=True)
            # Fail-open: allow acceptance even if validation fails

        try:
            suggestion = AICIDSuggestion.objects.get(id=suggestion_id, encounter=encounter)
        except AICIDSuggestion.DoesNotExist:
            return Response(
                {"error": "Sugestão não encontrada nesta consulta."},
                status=status.HTTP_404_NOT_FOUND,
            )

        suggestion.accepted_code = code
        suggestion.save(update_fields=["accepted_code"])

        # Update Encounter diagnosis if field exists (guard for schema evolution)
        encounter_updated = False
        if hasattr(encounter, "diagnosis_cid10"):
            encounter.diagnosis_cid10 = code
            encounter.save(update_fields=["diagnosis_cid10"])
            encounter_updated = True
        elif hasattr(encounter, "soap_note"):
            # Append to SOAPNote.cid10_codes list if not already present
            try:
                soap = encounter.soap_note
                current_codes = soap.cid10_codes or []
                if code not in current_codes:
                    current_codes.append(code)
                    soap.cid10_codes = current_codes
                    soap.save(update_fields=["cid10_codes"])
                    encounter_updated = True
            except Exception:
                logger.debug("Could not update SOAP note CID10 codes", exc_info=True)

        logger.info(
            "CID10 suggestion %s accepted (code=%s, encounter=%s, encounter_updated=%s)",
            suggestion_id,
            code,
            encounter_id,
            encounter_updated,
        )

        return Response(
            {
                "message": "Código CID-10 aceito com sucesso.",
                "code": code,
                "encounter_updated": encounter_updated,
            },
            status=status.HTTP_200_OK,
        )
