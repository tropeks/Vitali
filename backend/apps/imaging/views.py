"""
REST views for the imaging (DICOM Study tracking) module.

Endpoints:
- `GET    /api/v1/imaging/studies/?patient=…&modality=…&_count=…` — list
- `POST   /api/v1/imaging/studies/`                              — register
- `GET    /api/v1/imaging/studies/{id}/`                         — read
- `PATCH  /api/v1/imaging/studies/{id}/orthanc/`                 — backfill
                                                                   orthanc UID
- `POST   /api/v1/imaging/orthanc/webhook/`                      — Orthanc push

The user-facing endpoints are gated by the `imaging` module FeatureFlag
(default OFF) plus `imaging.read` / `imaging.write` permissions. The Orthanc
webhook is server-to-server (shared-secret), not a user session.
"""

from __future__ import annotations

import hmac
import logging
import re

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, IsPlatformAdmin, ModuleRequiredPermission

from .models import DicomStudy
from .serializers import (
    DicomStudyCreateSerializer,
    DicomStudyOrthancPatchSerializer,
    DicomStudySerializer,
)

logger = logging.getLogger(__name__)

_IMAGING_MODULE = ModuleRequiredPermission("imaging")


class StudyListCreateView(APIView):
    """GET / POST `/api/v1/imaging/studies/`."""

    DEFAULT_COUNT = 50
    MAX_COUNT = 200

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                IsAuthenticated(),
                _IMAGING_MODULE,
                HasPermission("imaging.write"),
            ]
        return [IsAuthenticated(), _IMAGING_MODULE, HasPermission("imaging.read")]

    def get(self, request):
        qs = DicomStudy.objects.select_related("patient").all()
        patient = request.query_params.get("patient")
        modality = request.query_params.get("modality")
        encounter = request.query_params.get("encounter")
        if patient:
            qs = qs.filter(patient_id=patient)
        if modality:
            qs = qs.filter(modality=modality.upper())
        if encounter:
            qs = qs.filter(encounter_id=encounter)
        try:
            count = min(int(request.query_params.get("_count", self.DEFAULT_COUNT)), self.MAX_COUNT)
        except (TypeError, ValueError):
            count = self.DEFAULT_COUNT
        if count < 1:
            count = self.DEFAULT_COUNT
        return Response(DicomStudySerializer(qs[:count], many=True).data)

    def post(self, request):
        serializer = DicomStudyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        study = serializer.save(created_by=request.user)
        return Response(DicomStudySerializer(study).data, status=status.HTTP_201_CREATED)


class StudyDetailView(APIView):
    """GET `/api/v1/imaging/studies/{id}/`."""

    def get_permissions(self):
        return [IsAuthenticated(), _IMAGING_MODULE, HasPermission("imaging.read")]

    def get(self, request, study_id):
        try:
            study = DicomStudy.objects.select_related("patient").get(pk=study_id)
        except (DicomStudy.DoesNotExist, ValueError):
            return Response({"detail": "Study not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(DicomStudySerializer(study).data)


class StudyOrthancBackfillView(APIView):
    """PATCH `/api/v1/imaging/studies/{id}/orthanc/` — set the Orthanc UID."""

    def get_permissions(self):
        return [IsAuthenticated(), _IMAGING_MODULE, HasPermission("imaging.write")]

    def patch(self, request, study_id):
        try:
            study = DicomStudy.objects.get(pk=study_id)
        except (DicomStudy.DoesNotExist, ValueError):
            return Response({"detail": "Study not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = DicomStudyOrthancPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        study.orthanc_study_id = data["orthanc_study_id"]
        if "number_of_series" in data:
            study.number_of_series = data["number_of_series"]
        if "number_of_instances" in data:
            study.number_of_instances = data["number_of_instances"]
        study.save(
            update_fields=[
                "orthanc_study_id",
                "number_of_series",
                "number_of_instances",
            ]
        )
        return Response(DicomStudySerializer(study).data)


class OrthancSyncTriggerView(APIView):
    """POST `/api/v1/imaging/orthanc/sync/` — run one ingestion pass on demand.

    Convenience for operators/admins to backfill immediately instead of waiting
    for the periodic beat tick. Platform-admin only. No-ops (200) when
    ``ORTHANC_URL`` is unset.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _IMAGING_MODULE, IsPlatformAdmin()]

    def post(self, request):
        from django.conf import settings

        from .services.orthanc_client import OrthancError
        from .services.orthanc_sync import sync_orthanc_studies

        if not getattr(settings, "ORTHANC_URL", ""):
            return Response(
                {"detail": "Orthanc not configured (ORTHANC_URL empty).", "inert": True},
                status=status.HTTP_200_OK,
            )
        try:
            summary = sync_orthanc_studies()
        except OrthancError as exc:
            return Response(
                {"detail": f"Orthanc unreachable: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(summary)


class OrthancWebhookView(APIView):
    """POST `/api/v1/imaging/orthanc/webhook/` — Orthanc → Vitali push ingestion.

    Called server-to-server by the Orthanc PACS (via its ``OnStableStudy`` Lua
    hook) the instant a study becomes stable, so ``orthanc_study_id`` is
    backfilled immediately instead of waiting for the periodic poll. It
    complements — does not replace — the Celery poller, which stays as the
    catch-up / replay path (e.g. studies that landed while Vitali was down).

    **Auth is a shared secret, not a user session.** Orthanc is trusted infra
    configured by the operator, so the endpoint authenticates the caller with a
    constant-time compare of the ``X-Orthanc-Webhook-Secret`` header against
    ``settings.ORTHANC_WEBHOOK_SECRET``. It is inert (``200``) when
    ``ORTHANC_URL`` is empty and refuses (``503``) when no secret is configured,
    so it can never run unauthenticated.

    **Multi-tenant.** When served on the public-schema host it fans out across
    every tenant (like the poller); on a tenant host it scopes to that tenant.
    Either way it only backfills pre-existing rows — never auto-creates (see
    ``orthanc_sync`` for the rationale).
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    # Orthanc resource ids are hex, optionally dash-grouped. Constrain the id
    # before it is interpolated into the Orthanc REST path (defence in depth
    # against path traversal even though the caller is already authenticated).
    _ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

    def post(self, request):
        from .services.orthanc_client import OrthancError
        from .services.orthanc_sync import ingest_one_study

        if not getattr(settings, "ORTHANC_URL", ""):
            return Response(
                {"detail": "Orthanc not configured (ORTHANC_URL empty).", "inert": True},
                status=status.HTTP_200_OK,
            )

        secret = getattr(settings, "ORTHANC_WEBHOOK_SECRET", "")
        if not secret:
            logger.error("orthanc webhook hit but ORTHANC_WEBHOOK_SECRET is unset — refusing")
            return Response(
                {"detail": "Webhook secret not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        presented = request.headers.get("X-Orthanc-Webhook-Secret", "")
        if not hmac.compare_digest(presented, secret):
            return Response(
                {"detail": "Invalid webhook secret."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = request.data if isinstance(request.data, dict) else {}
        orthanc_id = str(data.get("orthanc_study_id") or data.get("ID") or "").strip()
        if not self._ID_RE.match(orthanc_id):
            return Response(
                {"detail": "Missing or malformed orthanc_study_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            outcome = ingest_one_study(orthanc_id)
        except OrthancError as exc:
            logger.warning("orthanc webhook: study %s unreachable: %s", orthanc_id, exc)
            return Response(
                {"detail": f"Orthanc unreachable: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        logger.info("orthanc webhook: study %s → %s", orthanc_id, outcome)
        return Response({"orthanc_study_id": orthanc_id, "outcome": outcome})
