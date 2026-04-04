"""
Billing Views — TISS/TUSS
"""

import logging
from pathlib import Path

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.utils import timezone
from decimal import Decimal

from django.db.models import Count, Sum
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import TUSSCode
from apps.core.permissions import ModuleRequiredPermission

from .models import Glosa, InsuranceProvider, PriceTable, PriceTableItem, TISSBatch, TISSGuide
from .permissions import IsFaturistaOrAdmin
from .serializers import (
    GlosaSerializer,
    InsuranceProviderSerializer,
    PriceTableItemSerializer,
    PriceTableListSerializer,
    PriceTableSerializer,
    TISSBatchSerializer,
    TISSGuideListSerializer,
    TISSGuideSerializer,
    TUSSCodeSerializer,
)

logger = logging.getLogger(__name__)

_BILLING_MODULE = ModuleRequiredPermission("billing")


class TUSSCodePagination(PageNumberPagination):
    """50 results per page for combobox use. Safety net against dumping 6-8k rows."""
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class TUSSCodeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Search and retrieve TUSS codes from the shared (public-schema) table.
    Supports full-text search via ?search=<query>.
    Not gated by billing module — TUSS lookup is used in guide creation forms
    and should be accessible to any authenticated user.
    """

    serializer_class = TUSSCodeSerializer
    permission_classes = [IsAuthenticated, IsFaturistaOrAdmin]
    pagination_class = TUSSCodePagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "description", "group"]
    ordering_fields = ["code", "description"]
    ordering = ["code"]

    def get_queryset(self):
        qs = TUSSCode.objects.filter(active=True)
        q = self.request.query_params.get("q")
        if q:
            # Full-text search via GIN index when query provided
            query = SearchQuery(q, config="portuguese")
            qs = (
                qs.filter(search_vector=query)
                .annotate(rank=SearchRank("search_vector", query))
                .order_by("-rank")
            )
        return qs


class InsuranceProviderViewSet(viewsets.ModelViewSet):
    serializer_class = InsuranceProviderSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "ans_code", "cnpj"]
    ordering = ["name"]

    def get_queryset(self):
        return InsuranceProvider.objects.all()


class PriceTableViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "provider__name"]
    ordering = ["-valid_from"]

    def get_queryset(self):
        qs = PriceTable.objects.select_related("provider").annotate(item_count=Count("items"))
        provider = self.request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider=provider)
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return PriceTableListSerializer
        return PriceTableSerializer

    @action(detail=True, methods=["get", "post"], url_path="items")
    def items(self, request, pk=None):
        table = self.get_object()
        if request.method == "GET":
            items = table.items.select_related("tuss_code")
            serializer = PriceTableItemSerializer(items, many=True)
            return Response(serializer.data)
        # POST — add item
        serializer = PriceTableItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(table=table)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["put", "patch", "delete"],
        url_path=r"items/(?P<item_pk>\d+)",
    )
    def item_detail(self, request, pk=None, item_pk=None):
        table = self.get_object()
        try:
            item = table.items.get(pk=item_pk)
        except PriceTableItem.DoesNotExist:
            raise Http404
        if request.method == "DELETE":
            item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = PriceTableItemSerializer(
            item, data=request.data, partial=(request.method == "PATCH")
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TISSGuideViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["guide_number", "patient__full_name", "provider__name"]
    ordering_fields = ["created_at", "updated_at", "total_value", "competency"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        qs = TISSGuide.objects.select_related("patient", "provider", "price_table", "encounter")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        provider = self.request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider=provider)
        competency = self.request.query_params.get("competency")
        if competency:
            qs = qs.filter(competency=competency)
        encounter = self.request.query_params.get("encounter")
        if encounter:
            qs = qs.filter(encounter=encounter)
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return TISSGuideListSerializer
        return TISSGuideSerializer

    def perform_create(self, serializer):
        guide = serializer.save()
        # Link any GlosaPrediction rows that were shown before guide submission.
        # Only link rows that are still orphaned (guide__isnull=True) — prevents
        # a malicious or buggy client from hijacking predictions from another guide.
        glosa_prediction_ids = serializer.validated_data.get('glosa_prediction_ids', [])
        if glosa_prediction_ids:
            from apps.ai.models import GlosaPrediction
            GlosaPrediction.objects.filter(
                id__in=glosa_prediction_ids,
                guide__isnull=True,
            ).update(guide=guide)

    @action(detail=True, methods=["post"], url_path="generate-xml")
    def generate_xml(self, request, pk=None):
        """Generate TISS XML for a single guide and validate against XSD."""
        from .services.xml_engine import generate_guide_xml, validate_xml

        guide = self.get_object()
        try:
            xml_string = generate_guide_xml(guide)
            errors = validate_xml(xml_string)
            guide.xml_content = xml_string
            guide.save(update_fields=["xml_content", "updated_at"])
            return Response(
                {
                    "guide_number": guide.guide_number,
                    "xml": xml_string,
                    "validation_errors": errors,
                    "valid": not errors,
                }
            )
        except Exception as exc:
            logger.exception("XML generation failed for guide %s", guide.guide_number)
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """Mark guide as submitted (status: pending → submitted)."""
        from apps.core.signals import _write_audit

        guide = self.get_object()
        if guide.status not in ("draft", "pending"):
            return Response(
                {"detail": f"Cannot submit guide with status '{guide.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        old_status = guide.status
        guide.status = "submitted"
        guide.save(update_fields=["status", "updated_at"])
        _write_audit(
            f"guide_{guide.guide_number}_status_{old_status}→submitted",
            "tiss_guide",
            str(guide.pk),
            old_data={"status": old_status},
            new_data={"status": "submitted"},
        )
        return Response(TISSGuideSerializer(guide).data)


class TISSBatchViewSet(viewsets.ModelViewSet):
    serializer_class = TISSBatchSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "total_value"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = TISSBatch.objects.select_related("provider").prefetch_related("guides")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        provider = self.request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider=provider)
        return qs

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        """Close a batch (open → closed). Recalculates total_value atomically."""
        from django.db import transaction as db_transaction

        batch = self.get_object()
        if batch.status != "open":
            return Response(
                {"detail": f"Batch is already '{batch.status}', cannot close."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with db_transaction.atomic():
            total = batch.guides.aggregate(total=Sum("total_value"))["total"] or Decimal("0")
            batch.status = "closed"
            batch.closed_at = timezone.now()
            batch.total_value = total
            batch.save(update_fields=["status", "closed_at", "total_value"])
            batch.guides.filter(status="pending").update(status="submitted")
        return Response(TISSBatchSerializer(batch).data)

    @action(detail=True, methods=["post"], url_path="export")
    def export(self, request, pk=None):
        """Generate and store the batch XML file. Returns download URL."""
        from .services.xml_engine import generate_batch_xml, validate_xml

        batch = self.get_object()
        if batch.status == "open":
            return Response(
                {"detail": "Batch must be closed before export."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not batch.guides.exists():
            return Response(
                {"detail": "Cannot export an empty batch (no guides)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            xml_string = generate_batch_xml(batch)
            errors = validate_xml(xml_string)
            file_path = f"billing/batches/{batch.batch_number}.xml"
            actual_path = default_storage.save(file_path, ContentFile(xml_string.encode()))
            batch.xml_file = actual_path
            batch.save(update_fields=["xml_file"])
            return Response(
                {
                    "batch_number": batch.batch_number,
                    "file_path": file_path,
                    "validation_errors": errors,
                    "valid": not errors,
                    "download_url": request.build_absolute_uri(
                        f"/api/v1/billing/batches/{batch.pk}/download/"
                    ),
                }
            )
        except Exception as exc:
            logger.exception("Batch XML export failed for %s", batch.batch_number)
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Download the batch XML file."""
        batch = self.get_object()
        if not batch.xml_file:
            return Response(
                {"detail": "No XML file has been exported yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not default_storage.exists(batch.xml_file):
            return Response(
                {"detail": "XML file not found on storage."},
                status=status.HTTP_404_NOT_FOUND,
            )
        file_handle = default_storage.open(batch.xml_file)
        filename = Path(batch.xml_file).name
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=filename,
            content_type="application/xml",
        )

    @action(detail=True, methods=["post"], url_path="retorno")
    def upload_retorno(self, request, pk=None):
        """
        Upload a TISS retorno XML file for a specific batch.
        Parses the file, confirms it matches this batch's number, updates
        guide statuses, and creates Glosa records.
        URL: POST /api/v1/billing/batches/{id}/retorno/
        """
        from .services.retorno_parser import parse_retorno

        _MAX_RETORNO_BYTES = 10 * 1024 * 1024  # 10 MB — enough for any realistic TISS retorno

        batch = self.get_object()

        # Idempotency guard — prevent double-processing the same batch
        if batch.retorno_xml_file and not request.query_params.get("force"):
            return Response(
                {"detail": "Retorno já processado para este lote. Use ?force=true para reprocessar."},
                status=status.HTTP_409_CONFLICT,
            )

        uploaded = request.FILES.get("retorno_xml")
        if not uploaded:
            return Response(
                {"detail": "retorno_xml file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded.size > _MAX_RETORNO_BYTES:
            return Response(
                {"detail": f"retorno_xml too large ({uploaded.size} bytes). Maximum is 10 MB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        xml_bytes = uploaded.read()
        result = parse_retorno(xml_bytes)
        # Safety check: retorno must match this batch
        if result.get("batch_number") and result["batch_number"] != batch.batch_number:
            return Response(
                {
                    "detail": (
                        f"Retorno batch number '{result['batch_number']}' does not match "
                        f"this batch '{batch.batch_number}'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Store raw retorno XML for audit trail (plan requirement)
        retorno_path = f"billing/batches/{batch.batch_number}_retorno.xml"
        actual_retorno_path = default_storage.save(retorno_path, ContentFile(xml_bytes))
        batch.retorno_xml_file = actual_retorno_path
        batch.save(update_fields=["retorno_xml_file"])
        http_status = status.HTTP_200_OK if not result["errors"] else status.HTTP_207_MULTI_STATUS
        return Response(result, status=http_status)


class GlosaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Glosas are created only by the retorno parser (system), not by API clients.
    Use GET to list/retrieve and POST /appeal/ to file an appeal.
    """
    serializer_class = GlosaSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Glosa.objects.select_related("guide", "guide_item")
        guide = self.request.query_params.get("guide")
        if guide:
            qs = qs.filter(guide=guide)
        appeal_status = self.request.query_params.get("appeal_status")
        if appeal_status:
            qs = qs.filter(appeal_status=appeal_status)
        return qs

    @action(detail=True, methods=["post"], url_path="appeal")
    def appeal(self, request, pk=None):
        """File an appeal for a glosa."""
        glosa = self.get_object()
        if glosa.appeal_status == "filed":
            return Response(
                {"detail": "Appeal already filed for this glosa. Cannot refile."},
                status=status.HTTP_409_CONFLICT,
            )
        text = request.data.get("appeal_text", "").strip()
        if not text:
            return Response(
                {"detail": "appeal_text is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.core.signals import _write_audit

        glosa.appeal_status = "filed"
        glosa.appeal_text = text
        glosa.appeal_filed_at = timezone.now()
        glosa.save(update_fields=["appeal_status", "appeal_text", "appeal_filed_at"])
        # Update the guide status to 'appeal'
        old_status = glosa.guide.status
        glosa.guide.status = "appeal"
        glosa.guide.save(update_fields=["status", "updated_at"])
        _write_audit(
            f"guide_{glosa.guide.guide_number}_status_{old_status}→appeal",
            "tiss_guide",
            str(glosa.guide.pk),
            old_data={"status": old_status},
            new_data={"status": "appeal", "glosa_id": glosa.pk},
        )
        return Response(GlosaSerializer(glosa).data)
