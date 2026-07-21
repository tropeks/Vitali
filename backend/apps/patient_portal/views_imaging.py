"""Self-only diagnostic imaging endpoints for the patient portal."""

import re
from urllib.parse import parse_qs, unquote, urlsplit

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission, ModuleRequiredPermission
from apps.core.utils import tenant_has_feature
from apps.imaging.models import DicomStudy

from .models import PatientPortalAccess
from .serializers_imaging import PortalImagingReportSerializer, PortalImagingStudySerializer
from .views import _SelfView


def _patient_studies(patient):
    """The sole queryset boundary for patient-facing imaging data."""
    return DicomStudy.objects.filter(patient=patient).select_related(
        "report_document", "report_document__signed_by"
    )


class MeImagingStudiesView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        studies = _patient_studies(patient).order_by("-study_date")[:100]
        return Response(PortalImagingStudySerializer(studies, many=True).data)


class MeImagingStudyAuthorizationView(_SelfView):
    """Ownership check intended for a per-study viewer proxy subrequest."""

    def get(self, request, study_id):
        patient = self._patient(request)
        exists = _patient_studies(patient).filter(pk=study_id, orthanc_study_id__gt="").exists()
        if not exists:
            # Deliberately indistinguishable from a missing study (anti-IDOR).
            return Response({"detail": "Exame não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeImagingViewerAuthorizationView(APIView):
    """Authorize an OHIF/DICOMweb proxy request without exposing other patients.

    nginx must copy the original request URI into ``X-Original-URI``. Static
    viewer assets are safe after portal authentication. Viewer launches and
    every DICOMweb request must carry a StudyInstanceUID that belongs to the
    linked patient; generic QIDO study listing is deliberately denied.
    """

    permission_classes = [IsAuthenticated]
    _STUDY_PATH_RE = re.compile(r"(?:^|/)studies/([^/?]+)", re.IGNORECASE)
    _STAFF_MODULE = ModuleRequiredPermission("imaging")
    _STAFF_PERMISSION = HasPermission("imaging.read")

    def get(self, request):
        original_uri = request.headers.get("X-Original-URI", "")
        if not original_uri.startswith(("/visualizador/", "/imagens-dicom/")):
            return Response(status=status.HTTP_403_FORBIDDEN)

        # Clinical users retain their tenant module + RBAC authorization.
        if self._STAFF_MODULE.has_permission(request, self) and self._STAFF_PERMISSION.has_permission(
            request, self
        ):
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Patient users are confined to the active portal binding below.
        access = getattr(request.user, "patient_portal_access", None)
        role = request.user.effective_role()
        if (
            access is None
            or access.status != PatientPortalAccess.STATUS_ACTIVE
            or role is None
            or "portal.self_access" not in role.permissions
            or not tenant_has_feature(request.tenant, "patient_portal")
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)
        patient = access.patient

        parsed = urlsplit(original_uri)
        params = parse_qs(parsed.query)
        requested_uids = params.get("StudyInstanceUIDs", []) + params.get("StudyInstanceUID", [])
        # Never authorize a multi-study QIDO query: validating one value while
        # the archive honours another would be a classic confused-deputy IDOR.
        if len(requested_uids) > 1:
            return Response(status=status.HTTP_403_FORBIDDEN)
        uid = requested_uids[0] if requested_uids else ""
        path_match = self._STUDY_PATH_RE.search(parsed.path)
        if not uid and path_match:
            uid = unquote(path_match.group(1))

        # OHIF JS/CSS/config assets contain no patient data. A viewer launch,
        # however, is resource-scoped just like WADO/QIDO.
        if parsed.path.startswith("/visualizador/") and "/viewer" not in parsed.path:
            return Response(status=status.HTTP_204_NO_CONTENT)
        if not uid:
            return Response(status=status.HTTP_403_FORBIDDEN)

        owns_study = (
            _patient_studies(patient)
            .filter(study_instance_uid=uid, orthanc_study_id__gt="")
            .exists()
        )
        if not owns_study:
            # auth_request accepts only 2xx/401/403; use the same 403 for a
            # missing and a foreign UID so ownership cannot be enumerated.
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeImagingReportView(_SelfView):
    def get(self, request, study_id):
        patient = self._patient(request)
        try:
            study = _patient_studies(patient).get(
                pk=study_id,
                report_document__isnull=False,
                report_document__signed_at__isnull=False,
            )
        except (DicomStudy.DoesNotExist, ValueError):
            return Response({"detail": "Laudo não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        report = study.report_document
        AuditLog.objects.create(
            user=request.user,
            action="portal_imaging_report_viewed",
            resource_type="ClinicalDocument",
            resource_id=str(report.id),
            old_data={},
            new_data={"study_id": str(study.id)},
        )
        return Response(PortalImagingReportSerializer(report).data)
