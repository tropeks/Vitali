from django.http import HttpResponse
from rest_framework.response import Response

from apps.core.models import AuditLog
from apps.emr.models import LabOrder
from apps.signatures.models import LabReportArtifact

from .serializers_lab import PortalLabOrderSerializer
from .views import _SelfView


class MeLabResultsView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        qs = (
            LabOrder.objects.filter(
                patient=patient, status=LabOrder.Status.COMPLETED, report_artifact__isnull=False
            )
            .prefetch_related("items")
            .order_by("-completed_at")[:100]
        )
        return Response(PortalLabOrderSerializer(qs, many=True).data)


class MeLabReportPDFView(_SelfView):
    def get(self, request, order_id):
        patient = self._patient(request)
        try:
            artifact = LabReportArtifact.objects.select_related("order", "signature").get(
                order_id=order_id, order__patient=patient, order__status=LabOrder.Status.COMPLETED
            )
        except (LabReportArtifact.DoesNotExist, ValueError):
            return Response({"detail": "Laudo não encontrado."}, status=404)
        AuditLog.objects.create(
            user=request.user,
            action="portal_lab_report_downloaded",
            resource_type="LabOrder",
            resource_id=str(order_id),
            old_data={},
            new_data={"sha256": artifact.signature.document_hash_hex},
        )
        response = HttpResponse(bytes(artifact.pdf), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="laudo-{order_id}.pdf"'
        response["X-Document-SHA256"] = artifact.signature.document_hash_hex
        return response
