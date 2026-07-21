import base64

from django.db import transaction
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission, ModuleRequiredPermission
from apps.signatures.models import DigitalSignature, LabReportArtifact
from apps.signatures.services.icp_brasil import ICPBrasilSigner, ICPBrasilSignerError

from .lab_reports import render_lab_report_pdf
from .models import LabOrder

_EMR_MODULE = ModuleRequiredPermission("emr")


def _order(order_id):
    return LabOrder.objects.select_related("patient").prefetch_related("items").get(pk=order_id)


class LabReportSignView(APIView):
    def get_permissions(self):
        return [IsAuthenticated(), _EMR_MODULE, HasPermission("emr.write")]

    @transaction.atomic
    def post(self, request, order_id):
        try:
            order = _order(order_id)
        except (LabOrder.DoesNotExist, ValueError):
            return Response({"detail": "Pedido não encontrado."}, status=404)
        if order.status != LabOrder.Status.COMPLETED:
            return Response(
                {"detail": "Apenas pedidos concluídos podem ser liberados."}, status=409
            )
        if LabReportArtifact.objects.filter(order=order).exists():
            return Response({"detail": "Laudo já assinado e liberado."}, status=409)
        try:
            pfx = base64.b64decode(request.data.get("pkcs12_b64", ""), validate=True)
        except (ValueError, base64.binascii.Error):
            return Response({"pkcs12_b64": "Certificado inválido."}, status=400)
        pdf = render_lab_report_pdf(order)
        try:
            signed = ICPBrasilSigner.sign(pdf, pfx, request.data.get("pkcs12_password") or None)
        except ICPBrasilSignerError as exc:
            return Response({"detail": str(exc)}, status=400)
        signature = DigitalSignature.objects.create(
            document_type=DigitalSignature.DOCUMENT_TYPE_CUSTOM,
            document_id=str(order.id),
            signer=request.user,
            signature=signed.signature,
            signature_algorithm=signed.algorithm,
            document_hash_hex=signed.document_hash_hex,
            cert_subject=signed.cert_subject,
            cert_issuer=signed.cert_issuer,
            cert_serial_hex=signed.cert_serial_hex,
            cert_not_valid_before=signed.cert_not_valid_before,
            cert_not_valid_after=signed.cert_not_valid_after,
            is_icp_brasil=signed.is_icp_brasil,
        )
        artifact = LabReportArtifact.objects.create(
            order=order, signature=signature, pdf=pdf, released_by=request.user
        )
        AuditLog.objects.create(
            user=request.user,
            action="lab_report_released",
            resource_type="LabOrder",
            resource_id=str(order.id),
            old_data={},
            new_data={
                "artifact_id": str(artifact.id),
                "sha256": signed.document_hash_hex,
                "is_icp_brasil": signed.is_icp_brasil,
            },
        )
        return Response(
            {
                "id": artifact.id,
                "document_hash_hex": signed.document_hash_hex,
                "is_icp_brasil": signed.is_icp_brasil,
                "released_at": artifact.released_at,
            },
            status=status.HTTP_201_CREATED,
        )


class LabReportPDFView(APIView):
    def get_permissions(self):
        return [IsAuthenticated(), _EMR_MODULE, HasPermission("emr.read")]

    def get(self, request, order_id):
        try:
            artifact = LabReportArtifact.objects.select_related("order", "signature").get(
                order_id=order_id
            )
        except (LabReportArtifact.DoesNotExist, ValueError):
            return Response({"detail": "Laudo não liberado."}, status=404)
        response = HttpResponse(bytes(artifact.pdf), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="laudo-{artifact.order_id}.pdf"'
        response["X-Document-SHA256"] = artifact.signature.document_hash_hex
        return response
