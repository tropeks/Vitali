"""
Terminology catalog admin API (Sprint A1-T2 / A1-T3)
====================================================
Platform-admin surface over the SHARED governed terminology catalogs (CBO, CNES,
LOINC, UCUM). Three capabilities:

* **List / paginate** each catalog (A1-T2) — one read-only list endpoint per
  catalog, paginated by the project's ``StandardResultsSetPagination``.
* **Import-status summary** (A1-T2) — per-system row count + last import run
  (time / status / version) read from the generic ``TerminologyImportLog``.
* **Trigger an import** (A1-T3) — POST a CSV upload; it is handed to the matching
  ``import_<system>`` management command (idempotent upsert + provenance log).

All endpoints are Vitali-platform-admin only (``IsPlatformAdmin`` → superuser).
The catalogs and their import logs live in the PUBLIC schema, so no tenant schema
switching is needed — these routes are mounted under ``urls_public``.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from django.core.management import call_command
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.cbo_cnes_models import CBOCode, CNESEstablishment
from apps.core.loinc_models import LoincCode, UcumUnit
from apps.core.permissions import IsPlatformAdmin
from apps.core.serializers_terminology import (
    CatalogImportStatusSerializer,
    CBOCodeSerializer,
    CNESEstablishmentSerializer,
    LoincCodeSerializer,
    UcumUnitSerializer,
)
from apps.core.terminology_base import TerminologyImportLog

logger = logging.getLogger(__name__)

_PLATFORM_PERMS = (IsAuthenticated, IsPlatformAdmin)

# system id → (catalog model, import management command). Single source of truth
# shared by the list views, the status summary and the import trigger.
_CATALOGS: dict[str, tuple[type, str]] = {
    "cbo": (CBOCode, "import_cbo"),
    "cnes": (CNESEstablishment, "import_cnes"),
    "loinc": (LoincCode, "import_loinc"),
    "ucum": (UcumUnit, "import_ucum"),
}


# ─── A1-T2: per-catalog list/paginate ─────────────────────────────────────────


@extend_schema(
    tags=["platform-terminology"],
    summary="List CBO occupation catalog (platform admin)",
    responses=CBOCodeSerializer(many=True),
)
class CBOCodeListView(generics.ListAPIView):
    """GET /api/v1/platform/terminology/cbo/ — paginated CBO catalog."""

    serializer_class = CBOCodeSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = CBOCode.objects.all().order_by("code")


@extend_schema(
    tags=["platform-terminology"],
    summary="List CNES establishment catalog (platform admin)",
    responses=CNESEstablishmentSerializer(many=True),
)
class CNESEstablishmentListView(generics.ListAPIView):
    """GET /api/v1/platform/terminology/cnes/ — paginated CNES catalog."""

    serializer_class = CNESEstablishmentSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = CNESEstablishment.objects.all().order_by("code")


@extend_schema(
    tags=["platform-terminology"],
    summary="List LOINC observation catalog (platform admin)",
    responses=LoincCodeSerializer(many=True),
)
class LoincCodeListView(generics.ListAPIView):
    """GET /api/v1/platform/terminology/loinc/ — paginated LOINC catalog."""

    serializer_class = LoincCodeSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = LoincCode.objects.all().order_by("code")


@extend_schema(
    tags=["platform-terminology"],
    summary="List UCUM unit catalog (platform admin)",
    responses=UcumUnitSerializer(many=True),
)
class UcumUnitListView(generics.ListAPIView):
    """GET /api/v1/platform/terminology/ucum/ — paginated UCUM catalog."""

    serializer_class = UcumUnitSerializer
    permission_classes = _PLATFORM_PERMS
    queryset = UcumUnit.objects.all().order_by("code")


# ─── A1-T2: import-status summary ─────────────────────────────────────────────


class CatalogImportStatusView(APIView):
    """GET /api/v1/platform/terminology/import-status/

    Per-catalog row count + last import run (time / status / version). Row counts
    come from the live catalog tables; last-import metadata from the generic
    ``TerminologyImportLog``. Platform admin only.
    """

    permission_classes = _PLATFORM_PERMS

    @extend_schema(
        tags=["platform-terminology"],
        summary="Terminology catalog import-status summary (platform admin)",
        responses=CatalogImportStatusSerializer(many=True),
    )
    def get(self, request):
        rows = []
        for system, (model, _cmd) in _CATALOGS.items():
            last = TerminologyImportLog.objects.filter(system=system).order_by("-ran_at").first()
            rows.append(
                {
                    "system": system,
                    "row_count": model.objects.count(),
                    "last_import_at": last.ran_at if last else None,
                    "last_import_status": last.status if last else None,
                    "last_import_version": last.version if last else None,
                }
            )
        return Response(CatalogImportStatusSerializer(rows, many=True).data)


# ─── A1-T3: trigger an import ─────────────────────────────────────────────────


class CatalogImportTriggerView(APIView):
    """POST /api/v1/platform/terminology/<system>/import/

    Trigger a catalog import from an uploaded CSV. The file is handed to the
    matching ``import_<system>`` management command (semicolon-delimited CSV,
    idempotent upsert, per-row isolation, provenance log). Platform admin only.

    Body: multipart/form-data with a ``file`` field (the CSV). Optional
    ``version`` form field labels the imported rows.
    """

    permission_classes = _PLATFORM_PERMS
    parser_classes = (MultiPartParser, FormParser)

    # management-command dest for the per-system data-version label.
    _VERSION_DEST = {
        "cbo": "cbo_version",
        "cnes": "cnes_version",
        "loinc": "loinc_version",
        "ucum": "ucum_version",
    }

    @extend_schema(
        tags=["platform-terminology"],
        summary="Trigger a terminology catalog import from a CSV upload (platform admin)",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "version": {"type": "string"},
                },
                "required": ["file"],
            }
        },
        responses={
            200: OpenApiResponse(description="Import ran; returns per-run counts + status."),
            400: OpenApiResponse(description="Missing file or import validation error."),
            404: OpenApiResponse(description="Unknown terminology system."),
        },
    )
    def post(self, request, system: str):
        entry = _CATALOGS.get(system)
        if entry is None:
            return Response(
                {"detail": f"Unknown terminology system: {system!r}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        _model, command = entry

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "A CSV 'file' upload is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        version = (request.data.get("version") or "").strip()

        # Persist the upload to a temp path the management command can open.
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=True) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp.flush()
            kwargs: dict = {"source": str(Path(tmp.name))}
            if version:
                kwargs[self._VERSION_DEST[system]] = version
            try:
                call_command(command, **kwargs)
            except Exception as exc:  # noqa: BLE001 — surface parse/validation errors as 400
                logger.warning(
                    "terminology.import.failed system=%s by=%s err=%s",
                    system,
                    getattr(request.user, "email", "?"),
                    exc,
                )
                return Response(
                    {"detail": f"Import failed: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        last = TerminologyImportLog.objects.filter(system=system).order_by("-ran_at").first()
        logger.info(
            "terminology.import.ok system=%s by=%s",
            system,
            getattr(request.user, "email", "?"),
        )
        payload: dict[str, object] = {"system": system, "detail": "Import completed."}
        if last is not None:
            payload.update(
                {
                    "status": last.status,
                    "row_count_total": last.row_count_total,
                    "row_count_added": last.row_count_added,
                    "row_count_updated": last.row_count_updated,
                    "row_count_errors": last.row_count_errors,
                }
            )
        return Response(payload)
