"""
S-065: DRF view for generating prescription PDFs.

Endpoint: GET /emr/prescriptions/{id}/pdf/

Sign gate: returns 403 if prescription is not signed.
Returns PDF bytes with Content-Disposition: attachment.
"""
import logging

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.emr.models import Prescription
from apps.emr.services.prescription_pdf import PrescriptionPDFGenerator

logger = logging.getLogger(__name__)


class PrescriptionPDFView(APIView):
    """
    GET /emr/prescriptions/{prescription_id}/pdf/

    Generates and returns a PDF for the given prescription.
    403 if not signed, 404 if not found.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, prescription_id):
        try:
            prescription = Prescription.objects.select_related(
                "patient",
                "encounter__professional__user",
            ).get(id=prescription_id)
        except Prescription.DoesNotExist:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Receita não encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not prescription.is_signed:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Assine a receita antes de imprimir"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            generator = PrescriptionPDFGenerator()
            pdf_bytes = generator.generate(prescription)
        except ValueError as exc:
            # Sign gate re-raised as ValueError
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except Exception as exc:
            logger.error(
                "PDF generation failed for prescription %s: %s",
                prescription_id,
                exc,
                exc_info=True,
            )
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Falha ao gerar PDF. Tente novamente."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Short ID for filename (first 8 chars of UUID)
        short_id = str(prescription.id)[:8]
        filename = f"receita_{short_id}.pdf"

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Content-Length"] = len(pdf_bytes)

        return response
