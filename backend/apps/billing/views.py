"""
Billing Views — TISS/TUSS
"""

import csv
import hashlib
import io
import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Count, Sum
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import TUSSCode
from apps.core.permissions import ModuleRequiredPermission

from .models import (
    AccountingCategory,
    AccountingEntry,
    AccountsReceivable,
    BankStatementImport,
    BankTransaction,
    CashFlowEntry,
    Glosa,
    GlosaSafetyAlert,
    InsuranceProvider,
    Payable,
    PriceTable,
    PriceTableItem,
    ProfessionalSettlement,
    TISSBatch,
    TISSGuide,
)
from .permissions import IsFaturistaOrAdmin
from .serializers import (
    AccountingCategorySerializer,
    AccountingEntrySerializer,
    AccountsReceivableSerializer,
    BankTransactionSerializer,
    CashFlowEntrySerializer,
    GlosaSerializer,
    InsuranceProviderSerializer,
    PayableSerializer,
    PriceTableItemSerializer,
    PriceTableListSerializer,
    PriceTableSerializer,
    ProfessionalSettlementSerializer,
    TISSBatchSerializer,
    TISSGuideListSerializer,
    TISSGuideSerializer,
    TUSSCodeSerializer,
)

logger = logging.getLogger(__name__)
_BILLING_MODULE = ModuleRequiredPermission("billing")


class BankStatementImportView(APIView):
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "Envie o arquivo no campo file."}, status=400)
        if upload.size > 10 * 1024 * 1024:
            return Response({"error": "Arquivo excede 10 MB."}, status=413)
        raw = upload.read()
        digest = hashlib.sha256(raw).hexdigest()
        existing = BankStatementImport.objects.filter(file_sha256=digest).first()
        if existing:
            return Response(
                {"id": str(existing.id), "status": existing.status, "duplicate": True}, status=200
            )
        ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        if ext not in {"csv", "ofx"}:
            return Response({"error": "Formato aceito: CSV ou OFX."}, status=415)
        imp = BankStatementImport.objects.create(
            filename=upload.name[:255], file_sha256=digest, format=ext, imported_by=request.user
        )
        try:
            rows = self._parse_csv(raw) if ext == "csv" else self._parse_ofx(raw)
            BankTransaction.objects.bulk_create(
                [
                    BankTransaction(
                        statement=imp,
                        external_id=str(r.get("id") or f"{digest[:16]}-{i}"),
                        occurred_at=datetime.combine(r["date"], datetime.min.time()),
                        amount=r["amount"],
                        description=str(r.get("description", ""))[:500],
                    )
                    for i, r in enumerate(rows)
                ],
                ignore_conflicts=True,
            )
            imp.status = "processed"
            imp.save(update_fields=["status"])
            from apps.core.signals import _write_audit

            _write_audit(
                "bank_statement_imported",
                "bank_statement_import",
                str(imp.id),
                new_data={"filename": imp.filename, "transactions": len(rows)},
            )
            return Response(
                {"id": str(imp.id), "status": imp.status, "transactions": len(rows)}, status=201
            )
        except (ValueError, UnicodeDecodeError) as exc:
            imp.status, imp.error = "failed", str(exc)[:1000]
            imp.save(update_fields=["status", "error"])
            return Response({"error": "Arquivo inválido.", "detail": imp.error}, status=400)

    @staticmethod
    def _parse_csv(raw):
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV sem cabeçalho")
        names = {n.strip().lower(): n for n in reader.fieldnames}

        def pick(row, *keys):
            for key in keys:
                if key in names and row.get(names[key]):
                    return row[names[key]]
            return ""

        out = []
        for row in reader:
            raw_date = pick(row, "date", "data", "transaction_date")
            raw_amount = pick(row, "amount", "valor", "value")
            if not raw_date or not raw_amount:
                continue
            try:
                d = datetime.strptime(raw_date.strip()[:10], "%Y-%m-%d").date()
            except ValueError:
                d = datetime.strptime(raw_date.strip()[:10], "%d/%m/%Y").date()
            amount = raw_amount.strip().replace("R$", "").replace(".", "").replace(",", ".")
            out.append(
                {
                    "id": pick(row, "id", "fitid", "nsu"),
                    "date": d,
                    "amount": amount,
                    "description": pick(row, "description", "descricao", "memo"),
                    "counterparty": pick(row, "counterparty", "favorecido", "payee"),
                }
            )
        return out

    @staticmethod
    def _parse_ofx(raw):
        text = raw.decode("utf-8-sig", errors="replace")
        rows = []
        for block in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, flags=re.I | re.S):

            def tag(name, block=block):
                m = re.search(rf"<{name}>([^<\r\n]+)", block, flags=re.I)
                return m.group(1).strip() if m else ""

            d = tag("DTPOSTED")[:8]
            if not d or not tag("TRNAMT"):
                continue
            rows.append(
                {
                    "id": tag("FITID"),
                    "date": datetime.strptime(d, "%Y%m%d").date(),
                    "amount": tag("TRNAMT"),
                    "description": tag("MEMO") or tag("NAME"),
                    "counterparty": tag("NAME"),
                }
            )
        return rows


class ProfessionalSettlementViewSet(viewsets.ModelViewSet):
    queryset = ProfessionalSettlement.objects.select_related("professional__user")
    serializer_class = ProfessionalSettlementSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filterset_fields = ["professional", "competency", "status"]

    def perform_create(self, serializer):
        obj = serializer.save()
        obj.recalculate()
        obj.save(update_fields=["gross_amount", "net_amount", "calculated_at"])

    @action(detail=True, methods=["post"])
    def recalculate(self, request, pk=None):
        obj = self.get_object()
        obj.recalculate()
        obj.save(update_fields=["gross_amount", "net_amount", "calculated_at"])
        return Response(self.get_serializer(obj).data)


class AccountsReceivableViewSet(viewsets.ModelViewSet):
    serializer_class = AccountsReceivableSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["guide__guide_number", "guide__patient__full_name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return AccountsReceivable.objects.select_related("guide__patient", "guide__provider").all()

    def perform_create(self, serializer):
        obj = serializer.save()
        from apps.core.signals import _write_audit

        _write_audit(
            "receivable_created",
            "accounts_receivable",
            str(obj.pk),
            new_data={"guide": obj.guide_id, "amount": str(obj.amount)},
        )

    @action(detail=True, methods=["post"])
    def mark_received(self, request, pk=None):
        obj = self.get_object()
        old = obj.status
        obj.status = "received"
        obj.received_at = timezone.now()
        obj.save(update_fields=["status", "received_at", "updated_at"])
        from apps.core.signals import _write_audit

        _write_audit(
            "receivable_received",
            "accounts_receivable",
            str(obj.pk),
            old_data={"status": old},
            new_data={"status": obj.status},
        )
        return Response(self.get_serializer(obj).data)


class AccountingCategoryViewSet(viewsets.ModelViewSet):
    queryset = AccountingCategory.objects.all()
    serializer_class = AccountingCategorySerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]


class AccountingEntryViewSet(viewsets.ModelViewSet):
    serializer_class = AccountingEntrySerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filterset_fields = ["kind", "competency", "unit", "cost_center", "reconciled"]

    def get_queryset(self):
        return AccountingEntry.objects.select_related("category", "receivable")

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        from apps.core.signals import _write_audit

        _write_audit(
            "accounting_entry_created",
            "accounting_entry",
            str(obj.pk),
            new_data={"amount": str(obj.amount), "kind": obj.kind},
        )

    @action(detail=False, methods=["get"])
    def dre(self, request):
        qs = self.get_queryset()
        start, end = request.query_params.get("start"), request.query_params.get("end")
        if start:
            qs = qs.filter(competency__gte=start)
        if end:
            qs = qs.filter(competency__lte=end)
        revenue = qs.filter(kind="revenue").aggregate(total=Sum("amount"))["total"] or Decimal("0")
        expense = qs.filter(kind="expense").aggregate(total=Sum("amount"))["total"] or Decimal("0")
        cash = CashFlowEntry.objects.exclude(status="cancelled")
        if start:
            cash = cash.filter(due_date__gte=start)
        if end:
            cash = cash.filter(due_date__lte=end)
        payables = Payable.objects.exclude(status="cancelled")
        if start:
            payables = payables.filter(due_date__gte=start)
        if end:
            payables = payables.filter(due_date__lte=end)
        cash_in = sum(
            (x.amount for x in cash if x.kind == "inflow" and x.status == "realized"), Decimal("0")
        )
        cash_out = sum(
            (x.amount for x in cash if x.kind == "outflow" and x.status == "realized"), Decimal("0")
        )
        payable_open = sum((x.amount for x in payables if x.status != "paid"), Decimal("0"))
        return Response(
            {
                "revenue": str(revenue),
                "expense": str(expense),
                "result": str(revenue - expense),
                "entries": qs.count(),
                "cash_realized_inflow": str(cash_in),
                "cash_realized_outflow": str(cash_out),
                "cash_realized_net": str(cash_in - cash_out),
                "payables_open": str(payable_open),
            }
        )


class BankTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = BankTransactionSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filterset_fields = ["status"]

    def get_queryset(self):
        return BankTransaction.objects.select_related("receivable", "matched_by")

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        from django.db import transaction

        with transaction.atomic():
            tx = (
                BankTransaction.objects.select_for_update()
                .select_related("receivable")
                .get(pk=self.get_object().pk)
            )
            return self._match_locked(request, tx)

    def _match_locked(self, request, tx):
        if tx.status == "matched":
            return Response(self.get_serializer(tx).data)
        candidates = AccountsReceivable.objects.filter(
            status__in=["expected", "billed", "overdue"], amount=tx.amount
        )
        desc = (tx.description or "").lower()
        candidate = next((r for r in candidates if r.guide.guide_number.lower() in desc), None)
        if candidate is None and candidates.count() == 1:
            candidate = candidates.first()
        if candidate is None:
            tx.status, tx.confidence = "review", 0
            tx.save(update_fields=["status", "confidence"])
            return Response(self.get_serializer(tx).data)
        tx.receivable, tx.confidence, tx.status = candidate, 100, "review"
        # A receivable can only be matched once; prevent concurrent bank rows
        # from silently double-allocating it.
        if (
            BankTransaction.objects.filter(receivable=candidate, status="matched")
            .exclude(pk=tx.pk)
            .exists()
        ):
            return Response({"detail": "Recebível já conciliado."}, status=409)
        tx.save(update_fields=["receivable", "confidence", "status"])
        return Response(self.get_serializer(tx).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        from django.db import transaction

        with transaction.atomic():
            tx = (
                BankTransaction.objects.select_for_update()
                .select_related("receivable")
                .get(pk=self.get_object().pk)
            )
            if tx.status == "matched":
                return Response(self.get_serializer(tx).data)
            if not tx.receivable:
                return Response({"detail": "Transação sem recebível conciliado."}, status=400)
            tx.status, tx.matched_at, tx.matched_by = "matched", timezone.now(), request.user
            tx.save(update_fields=["status", "matched_at", "matched_by"])
            rec = tx.receivable
            rec = AccountsReceivable.objects.select_for_update().get(pk=rec.pk)
            if rec.status == "received":
                return Response({"detail": "Recebível já baixado."}, status=409)
            rec.status, rec.received_at = "received", tx.matched_at
            rec.save(update_fields=["status", "received_at", "updated_at"])
            from apps.core.signals import _write_audit

            _write_audit(
                "receivable_settled",
                "accounts_receivable",
                str(rec.pk),
                new_data={"bank_transaction": str(tx.pk)},
            )
        return Response(self.get_serializer(tx).data)


class PayableViewSet(viewsets.ModelViewSet):
    serializer_class = PayableSerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filterset_fields = ["status", "category", "cost_center"]

    def get_queryset(self):
        return Payable.objects.select_related("created_by").all()

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        from apps.core.signals import _write_audit

        _write_audit(
            "payable_created", "payable", str(obj.pk), new_data={"amount": str(obj.amount)}
        )

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        with transaction.atomic():
            obj = Payable.objects.select_for_update().get(pk=self.get_object().pk)
            if obj.status == "cancelled":
                return Response({"detail": "Conta cancelada."}, status=400)
            if obj.status == "paid":
                return Response(self.get_serializer(obj).data)
            obj.status, obj.paid_at = "paid", timezone.now()
            obj.save(update_fields=["status", "paid_at", "updated_at"])
            CashFlowEntry.objects.update_or_create(
                external_id=f"payable:{obj.external_id}",
                defaults={
                    "description": obj.description,
                    "kind": "outflow",
                    "amount": obj.amount,
                    "due_date": obj.due_date,
                    "realized_at": obj.paid_at,
                    "category": obj.category,
                    "cost_center": obj.cost_center,
                    "status": "realized",
                },
            )
        from apps.core.signals import _write_audit

        _write_audit("payable_paid", "payable", str(obj.pk), new_data={"amount": str(obj.amount)})
        return Response(self.get_serializer(obj).data)


class CashFlowEntryViewSet(viewsets.ModelViewSet):
    serializer_class = CashFlowEntrySerializer
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filterset_fields = ["kind", "status", "category", "cost_center"]

    def get_queryset(self):
        return CashFlowEntry.objects.all()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.get_queryset().exclude(status="cancelled")
        return Response(
            {
                "forecast_inflow": str(
                    sum(
                        (x.amount for x in qs if x.kind == "inflow" and x.status == "forecast"),
                        Decimal("0"),
                    )
                ),
                "forecast_outflow": str(
                    sum(
                        (x.amount for x in qs if x.kind == "outflow" and x.status == "forecast"),
                        Decimal("0"),
                    )
                ),
                "realized_inflow": str(
                    sum(
                        (x.amount for x in qs if x.kind == "inflow" and x.status == "realized"),
                        Decimal("0"),
                    )
                ),
                "realized_outflow": str(
                    sum(
                        (x.amount for x in qs if x.kind == "outflow" and x.status == "realized"),
                        Decimal("0"),
                    )
                ),
            }
        )


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
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "ans_code", "cnpj"]
    ordering = ["name"]

    def get_queryset(self):
        return InsuranceProvider.objects.all()


class PriceTableViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
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
        except PriceTableItem.DoesNotExist as exc:
            raise Http404 from exc
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
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
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
        patient = self.request.query_params.get("patient")
        if patient:
            qs = qs.filter(patient_id=patient)
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
        # Pop write-only field before save so it doesn't reach TISSGuide.objects.create()
        glosa_prediction_ids = serializer.validated_data.pop("glosa_prediction_ids", [])
        guide = serializer.save()
        # Link any GlosaPrediction rows that were shown before guide submission.
        # Only link rows that are still orphaned (guide__isnull=True) — prevents
        # a malicious or buggy client from hijacking predictions from another guide.
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
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
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
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import transaction as db_transaction

        batch = self.get_object()
        if batch.status != "open":
            return Response(
                {"detail": f"Batch is already '{batch.status}', cannot close."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with db_transaction.atomic():
            # TOCTOU fix: lock the BATCH row first, then read its guide set from
            # the locked instance. Without the batch lock a concurrent
            # guides.add(new_guide) could slip an UNEVALUATED guide into the
            # batch between evaluation and the blocking-check (which reads
            # batch.guides.all()), letting an un-checked guide through the gate.
            # We evaluate exactly locked_batch.guides.all() and then run the
            # blocking-check over that SAME locked instance, so no guide can be
            # present-but-unevaluated.
            locked_batch = TISSBatch.objects.select_for_update().get(pk=batch.pk)

            # Re-validate double-submit at close time. Two batches can both be
            # left "open" with the same guide (the serializer/signal checks ran
            # while both were open and saw no *finalised* conflict); without this
            # re-check, closing both would export the guide in two XMLs → billed
            # twice (financial + ANS violation). Lock the candidate guides so a
            # concurrent close of a sibling batch cannot race past this check.
            #
            # Capture the guide id set ONCE under the batch-row lock. This is the
            # SET OF RECORD for the rest of close(): we evaluate exactly these
            # guides AND run the blocking-check over exactly these ids, so no
            # guide can be present-but-unevaluated. A membership re-assertion just
            # before finalize closes the add-after-capture window.
            locked_guides = list(locked_batch.guides.select_for_update())
            evaluated_ids = [g.pk for g in locked_guides]
            try:
                for guide in locked_guides:
                    # Only finalised batches (closed/submitted) constitute a real
                    # double-billing conflict at this point; another still-open
                    # batch holding the same guide is fine — whichever closes
                    # first wins, and the second close will then be rejected here.
                    # Cancelled batches never conflict.
                    locked_batch.check_guide_not_double_submitted(
                        guide, statuses=["closed", "submitted"]
                    )
            except DjangoValidationError as exc:
                # Surface model-layer ValidationError as an HTTP 400 (DRF) with a
                # clear PT-BR message instead of an uncaught 500.
                raise serializers.ValidationError({"guides": list(exc.messages)}) from exc

            # Glosa-safety soft-stop (wedge PR G1). No-op when the glosa_safety
            # feature flag is OFF for this tenant — gate behaves exactly as
            # before. PER-GUIA: evaluate each guide under the lock, then 409 with
            # ONLY the offending guides if any has an unacknowledged BLOCKING
            # alert. The faturista removes/acknowledges those guides and
            # re-closes; we do NOT close the batch nor block the clean guides.
            from .services.glosa_safety import GlosaSafetyService

            glosa_service = GlosaSafetyService(requesting_user=request.user)
            # Evaluate exactly the captured guide-id set...
            for guide in locked_guides:
                glosa_service.evaluate_guide(guide, gate="batch_close")
            # ...and check blocking alerts over the SAME id set (NOT a fresh
            # batch.guides.all() re-query), so the evaluated set and the checked
            # set are provably identical — a guide cannot be
            # present-but-unevaluated between the two steps.
            blocking = glosa_service.blocking_glosa_alerts_for_guides(evaluated_ids)
            if blocking:
                return Response(
                    self._glosa_block_payload(blocking),
                    status=status.HTTP_409_CONFLICT,
                )

            # Membership re-assertion: immediately before finalizing (batch row
            # still locked, same atomic block), re-read the batch's current guide
            # set. If it differs from the set we evaluated, a guide was
            # added/removed mid-close — finalizing now would close a
            # present-but-unevaluated guide. Reject with 409 instead; the
            # faturista re-closes and the new set is re-evaluated.
            current_ids = set(locked_batch.guides.values_list("pk", flat=True))
            if current_ids != set(evaluated_ids):
                return Response(
                    {
                        "code": "batch_modified_during_close",
                        "detail": (
                            "O lote foi modificado durante o fechamento; "
                            "reavalie e feche novamente."
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # Finalize STRICTLY over the evaluated id set — never re-query the
            # `.guides` relation here. Under READ COMMITTED a concurrent
            # guides.add() can commit between the re-assertion above and these
            # writes (Postgres FK FOR KEY SHARE does not conflict with the batch
            # row's FOR NO KEY UPDATE lock); a fresh `.guides` query would then
            # phantom-read that guide and bill/submit it WITHOUT it ever being
            # evaluated. Scoping to evaluated_ids makes that impossible: only the
            # guides we actually evaluated are summed and submitted.
            total = locked_batch.guides.filter(pk__in=evaluated_ids).aggregate(
                total=Sum("total_value")
            )["total"] or Decimal("0")
            locked_batch.status = "closed"
            locked_batch.closed_at = timezone.now()
            locked_batch.total_value = total
            locked_batch.save(update_fields=["status", "closed_at", "total_value"])
            locked_batch.guides.filter(pk__in=evaluated_ids, status="pending").update(
                status="submitted"
            )
        return Response(TISSBatchSerializer(locked_batch).data)

    @staticmethod
    def _glosa_block_payload(blocking):
        """Build the per-guia 409 body listing ONLY the offending guides and their
        unacknowledged blocking glosa alerts. ``blocking`` is the
        [(guide, [alert, ...]), ...] from blocking_glosa_alerts_for_batch."""
        return {
            "code": "glosa_safety_block",
            "detail": (
                "Há guias com risco de glosa bloqueante. Remova ou reconheça (com "
                "justificativa) as guias abaixo e feche o lote novamente."
            ),
            "guides": [
                {
                    "guide_id": str(guide.id),
                    "guide_number": guide.guide_number,
                    "alerts": [
                        {
                            "id": str(a.id),
                            "check_code": a.check_code,
                            "severity": a.severity,
                            "message": a.message,
                            "recommendation": a.recommendation,
                            "guide_item": str(a.guide_item_id)
                            if a.guide_item_id is not None
                            else None,
                        }
                        for a in alerts
                    ],
                }
                for guide, alerts in blocking
            ],
        }

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
                {
                    "detail": "Retorno já processado para este lote. Use ?force=true para reprocessar."
                },
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
    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]
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


# ─── S-055: PIX Payment Views ─────────────────────────────────────────────────

import hmac as _hmac  # noqa: E402
from decimal import Decimal as _Decimal  # noqa: E402

from django.conf import settings as _settings  # noqa: E402
from django.db import transaction  # noqa: E402

from .models import PIXCharge  # noqa: E402
from .services.asaas import AsaasAPIError, AsaasService  # noqa: E402


class PIXChargeCreateSerializer(serializers.Serializer):
    appointment_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=_Decimal("0.01"))


class PIXChargeView(APIView):
    """
    POST /api/v1/billing/pix/charges/  — create PIX charge
    GET  /api/v1/billing/pix/charges/:id/ — get charge status
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = PIXChargeCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "details": ser.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.emr.models import Appointment

        try:
            appointment = Appointment.objects.get(id=ser.validated_data["appointment_id"])
        except Appointment.DoesNotExist:
            return Response(
                {"error": {"code": "NOT_FOUND", "message": "Agendamento não encontrado."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Idempotent: return existing pending charge
        existing = PIXCharge.objects.filter(
            appointment=appointment, status=PIXCharge.Status.PENDING
        ).first()
        if existing:
            return Response(_pix_charge_dict(existing))

        try:
            service = AsaasService()
            charge_data = service.create_pix_charge(appointment, ser.validated_data["amount"])
        except AsaasAPIError as exc:
            return Response(exc.to_response_dict(), status=status.HTTP_503_SERVICE_UNAVAILABLE)

        from django.db import connection

        from apps.core.models import AsaasChargeMap

        with transaction.atomic():
            charge = PIXCharge.objects.create(
                appointment=appointment,
                asaas_charge_id=charge_data["asaas_charge_id"],
                asaas_customer_id=charge_data["asaas_customer_id"],
                amount=ser.validated_data["amount"],
                pix_copy_paste=charge_data["pix_copy_paste"],
                pix_qr_code_base64=charge_data["pix_qr_code_base64"],
                expires_at=charge_data["expires_at"],
            )
            AsaasChargeMap.objects.get_or_create(
                asaas_charge_id=charge_data["asaas_charge_id"],
                defaults={"tenant_schema": connection.schema_name},
            )
        return Response(_pix_charge_dict(charge), status=status.HTTP_201_CREATED)

    def get(self, request, charge_id=None):
        try:
            charge = PIXCharge.objects.get(id=charge_id)
        except PIXCharge.DoesNotExist:
            return Response(
                {"error": {"code": "NOT_FOUND", "message": "Cobrança não encontrada."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_pix_charge_dict(charge))


def _pix_charge_dict(charge: "PIXCharge") -> dict:
    return {
        "id": str(charge.id),
        "appointment_id": str(charge.appointment_id),
        "amount": str(charge.amount),
        "status": charge.status,
        "pix_copy_paste": charge.pix_copy_paste,
        "pix_qr_code_base64": charge.pix_qr_code_base64,
        "expires_at": charge.expires_at.isoformat(),
        "paid_at": charge.paid_at.isoformat() if charge.paid_at else None,
    }


class AsaasWebhookView(APIView):
    """
    POST /api/v1/billing/pix/webhook/
    Public endpoint — Asaas sends PAYMENT_RECEIVED events here.

    Security:
    - Validates asaas-access-token header (constant-time compare).
    - Validates charge exists in DB before acting (defense-in-depth).
    - select_for_update + status check = idempotent on duplicate delivery.
    Always returns 200 to prevent Asaas retry storms.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        token = request.headers.get("asaas-access-token", "")
        expected = getattr(_settings, "ASAAS_WEBHOOK_TOKEN", "")
        if not expected or not _hmac.compare_digest(token.encode(), expected.encode()):
            logger.warning("asaas.webhook.invalid_token ip=%s", request.META.get("REMOTE_ADDR"))
            return Response({"status": "ok"}, status=status.HTTP_401_UNAUTHORIZED)

        event_type = request.data.get("event", "")
        payment = request.data.get("payment", {})
        charge_id = payment.get("id", "")
        if event_type != "PAYMENT_RECEIVED" or not charge_id:
            return Response({"status": "ok"})

        from django_tenants.utils import schema_context

        from apps.core.models import AsaasChargeMap

        try:
            charge_map = AsaasChargeMap.objects.get(asaas_charge_id=charge_id)
        except AsaasChargeMap.DoesNotExist:
            logger.warning("asaas.webhook.unknown_charge charge_id=%s", charge_id)
            return Response({"status": "ok"})

        with schema_context(charge_map.tenant_schema):
            _process_pix_payment_received(charge_id)

        return Response({"status": "ok"})


def _process_pix_payment_received(charge_id: str) -> None:
    """Process PAYMENT_RECEIVED within the correct tenant schema. Idempotent."""
    with transaction.atomic():
        try:
            charge = PIXCharge.objects.select_for_update().get(
                asaas_charge_id=charge_id,
                status=PIXCharge.Status.PENDING,
            )
        except PIXCharge.DoesNotExist:
            logger.info("asaas.webhook.already_processed charge_id=%s", charge_id)
            return

        charge.status = PIXCharge.Status.PAID
        charge.paid_at = timezone.now()
        charge.save(update_fields=["status", "paid_at", "updated_at"])

        appointment = charge.appointment
        if appointment.status in ("scheduled", "waiting"):
            appointment.status = "confirmed"
            appointment.save(update_fields=["status", "updated_at"])

        from .services.pix_signals import appointment_paid

        appointment_paid.send(sender=PIXCharge, appointment=appointment)

    logger.info(
        "asaas.webhook.processed charge_id=%s appointment_id=%s",
        charge_id,
        str(charge.appointment_id),
    )


class AcknowledgeGlosaAlertView(APIView):
    """
    POST /api/v1/billing/glosa-safety-alerts/{alert_id}/acknowledge/

    Body: {reason: str}

    Mirrors emr.AcknowledgeSafetyAlertView. For severity="block" the reason is
    REQUIRED (min 10 chars) → 400 if missing. An "advise" alert acks without a
    reason. Sets status="acknowledged", acknowledged_by, override_reason,
    acknowledged_at. Same faturista/admin permission as the batch-close gate.
    """

    permission_classes = [IsAuthenticated, _BILLING_MODULE, IsFaturistaOrAdmin]  # type: ignore[list-item]

    def post(self, request, alert_id):
        reason = request.data.get("reason", "").strip()

        try:
            alert = GlosaSafetyAlert.objects.get(id=alert_id)
        except GlosaSafetyAlert.DoesNotExist:
            return Response(
                {"error": "Alerta não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only a flagged (open) alert is actionable; re-acking would overwrite the
        # original acknowledged_by/at and emit audit noise.
        if alert.status != GlosaSafetyAlert.Status.FLAGGED:
            return Response(
                {"error": "Alerta já reconhecido ou resolvido; nada a fazer."},
                status=status.HTTP_409_CONFLICT,
            )

        if alert.severity == GlosaSafetyAlert.Severity.BLOCK and len(reason) < 10:
            return Response(
                {"error": "Para bloqueios de glosa, o motivo deve ter pelo menos 10 caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        alert.acknowledge(request.user, reason)

        logger.info(
            "Glosa safety alert %s acknowledged by user %s (severity=%s)",
            alert.id,
            request.user.id,
            alert.severity,
        )

        return Response(
            {
                "message": "Alerta reconhecido com sucesso.",
                "alert_id": str(alert.id),
                "acknowledged_at": alert.acknowledged_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )
