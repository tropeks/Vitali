"""
Pharmacy API views — S-026 Catalog, S-027 Stock, S-028 Dispensation
"""

import hmac
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import (
    AllergenClass,
    ControlledAlert,
    Dispensation,
    DispensationLot,
    DoseRule,
    Drug,
    DrugInteraction,
    InventoryCount,
    LotRecall,
    Material,
    NFeCatalogMapping,
    NFeReceipt,
    NFeReceiptItem,
    PharmacistValidation,
    PurchaseOrder,
    PurchaseOrderItem,
    StockAlert,
    StockItem,
    StockMovement,
    StockReceipt,
    StockTransfer,
    StorageLocation,
    Supplier,
    SupplierContract,
    SupplierInvoice,
    ThreeWayMatch,
    Warehouse,
)
from .serializers import (
    AllergenClassSerializer,
    DispensationSerializer,
    DispenseRequestSerializer,
    DoseRuleSerializer,
    DrugInteractionSerializer,
    DrugSerializer,
    InventoryCountSerializer,
    LotRecallSerializer,
    MaterialSerializer,
    NFeCatalogMappingSerializer,
    NFeReceiptSerializer,
    PharmacistValidationSerializer,
    POReceiveSerializer,
    PurchaseOrderSerializer,
    StockItemSerializer,
    StockMovementSerializer,
    StockReceiptSerializer,
    StockTransferSerializer,
    StorageLocationSerializer,
    SupplierContractSerializer,
    SupplierInvoiceSerializer,
    SupplierSerializer,
    ThreeWayMatchSerializer,
    WarehouseSerializer,
)
from .services.enterprise_stock import InventoryService, TransferService
from .services.nfe_ingestion import ingest_xml

_PHARMACY_MODULE = ModuleRequiredPermission("pharmacy")


class NFeReceiptViewSet(viewsets.ModelViewSet):
    queryset = NFeReceipt.objects.prefetch_related("items")
    serializer_class = NFeReceiptSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_permissions(self):
        p = (
            "pharmacy.procurement_manage"
            if self.action not in {"list", "retrieve"}
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(p)]

    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if not upload or upload.size > 10 * 1024 * 1024 or not upload.name.lower().endswith(".xml"):
            return Response({"detail": "Envie um XML até 10 MB."}, status=400)
        raw = upload.read()
        try:
            receipt, created = ingest_xml(raw, source="manual", uploaded_by=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        if not created:
            return Response(self.get_serializer(receipt).data, status=409)
        return Response(self.get_serializer(receipt).data, status=201)

    # legacy parser retained below for compatibility is intentionally unreachable
    def _legacy_create(self, request, *args, **kwargs):
        return Response({"detail": "Endpoint legado desativado."}, status=410)

    @staticmethod
    def _suggest_mappings(receipt):
        for item in receipt.items.all():
            drug = material = None
            match = "manual"
            confidence = 0
            if item.barcode and (
                drug := Drug.objects.filter(barcode=item.barcode, is_active=True).first()
            ):
                match, confidence = "barcode", 100
            elif item.barcode and (
                material := Material.objects.filter(barcode=item.barcode, is_active=True).first()
            ):
                match, confidence = "barcode", 100
            elif item.supplier_code:
                drug = Drug.objects.filter(anvisa_code=item.supplier_code, is_active=True).first()
                if drug:
                    match, confidence = "supplier_code", 90
            if not (drug or material) and item.ncm:
                material = Material.objects.filter(
                    notes__icontains=item.ncm, is_active=True
                ).first()
                if material:
                    match, confidence = "ncm", 60
            if drug or material:
                NFeCatalogMapping.objects.update_or_create(
                    item=item,
                    defaults={
                        "drug": drug,
                        "material": material,
                        "match_type": match,
                        "confidence": confidence,
                    },
                )

    @action(detail=True, methods=("get",))
    def mappings(self, request, pk=None):
        return Response(
            NFeCatalogMappingSerializer(
                NFeCatalogMapping.objects.filter(item__receipt=self.get_object()).select_related(
                    "drug", "material"
                ),
                many=True,
            ).data
        )

    @action(detail=True, methods=("post",), url_path=r"items/(?P<item_id>[^/.]+)/map")
    def map_item(self, request, pk=None, item_id=None):
        item = get_object_or_404(NFeReceiptItem, receipt=self.get_object(), pk=item_id)
        drug_id = request.data.get("drug")
        material_id = request.data.get("material")
        if bool(drug_id) == bool(material_id):
            return Response(
                {"detail": "Informe exatamente um de drug ou material."}, status=400
            )
        try:
            if drug_id and not Drug.objects.filter(pk=drug_id).exists():
                return Response({"detail": "Medicamento não encontrado."}, status=400)
            if material_id and not Material.objects.filter(pk=material_id).exists():
                return Response({"detail": "Material não encontrado."}, status=400)
        except (ValueError, ValidationError):
            return Response({"detail": "Identificador de catálogo inválido."}, status=400)
        mapping, _ = NFeCatalogMapping.objects.update_or_create(
            item=item,
            defaults={
                "drug_id": drug_id,
                "material_id": material_id,
                "match_type": "manual",
                "confidence": 100,
                "status": "confirmed",
                "reviewed_by": request.user,
                "reviewed_at": timezone.now(),
            },
        )
        log_audit(
            request,
            "map_nfe_catalog",
            "NFeReceiptItem",
            item.id,
            new_data={"drug": str(mapping.drug_id), "material": str(mapping.material_id)},
        )
        return Response(NFeCatalogMappingSerializer(mapping).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        with transaction.atomic():
            receipt = NFeReceipt.objects.select_for_update().get(pk=self.get_object().pk)
            if receipt.status != "pending":
                return Response({"detail": "Status inválido."}, status=409)
            tenant_cnpj = getattr(getattr(request, "tenant", None), "cnpj", None)
            tenant_digits = "".join(ch for ch in (tenant_cnpj or "") if ch.isdigit())
            if not tenant_digits:
                # Fail closed: without a configured CNPJ we cannot prove the NF-e
                # was addressed to this clinic, so refuse instead of approving blindly.
                return Response(
                    {"detail": "CNPJ da clínica não configurado; configure antes de aprovar NF-e."},
                    status=409,
                )
            if "".join(ch for ch in receipt.recipient_cnpj if ch.isdigit()) != tenant_digits:
                return Response({"detail": "CNPJ destinatário não pertence à clínica."}, status=409)
            if (
                receipt.items.filter(catalog_mapping__isnull=True).exists()
                or receipt.items.exclude(catalog_mapping__status="confirmed").exists()
            ):
                return Response(
                    {"detail": "Todos os itens precisam de mapeamento confirmado."}, status=409
                )
            receipt.status, receipt.approved_by, receipt.approved_at = (
                "approved",
                request.user,
                timezone.now(),
            )
            receipt.save(update_fields=["status", "approved_by", "approved_at"])
        log_audit(
            request,
            "approve_nfe_receipt",
            "NFeReceipt",
            receipt.id,
            new_data={"status": "approved"},
        )
        return Response(self.get_serializer(receipt).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Reject/return a quarantined NF-e before stock is posted."""
        receipt = self.get_object()
        if receipt.status not in ("pending", "validated"):
            return Response({"detail": "A NF-e não pode mais ser devolvida."}, status=409)
        receipt.status = "rejected"
        receipt.validation_errors = [
            *receipt.validation_errors,
            request.data.get("reason", "Devolução solicitada na conferência"),
        ]
        receipt.save(update_fields=["status", "validation_errors"])
        log_audit(
            request, "reject_nfe_receipt", "NFeReceipt", receipt.id, new_data={"status": "rejected"}
        )
        return Response(self.get_serializer(receipt).data)


class NFeWebhookView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        expected = getattr(settings, "NFE_WEBHOOK_SECRET", "")
        supplied = request.headers.get("X-NFe-Webhook-Secret", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return Response({"detail": "Não autorizado."}, status=401)
        raw = request.body
        if len(raw) > 10 * 1024 * 1024:
            return Response({"detail": "XML excede 10 MB."}, status=413)
        try:
            receipt, created = ingest_xml(
                raw, source="webhook", external_id=request.headers.get("Idempotency-Key", "")
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            {"id": str(receipt.id), "status": receipt.status, "created": created},
            status=201 if created else 200,
        )


class SupplierContractViewSet(viewsets.ModelViewSet):
    queryset = SupplierContract.objects.select_related("supplier")
    serializer_class = SupplierContractSerializer

    def get_permissions(self):
        permission = (
            "pharmacy.procurement_manage"
            if self.action not in {"list", "retrieve"}
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SupplierInvoiceViewSet(viewsets.ModelViewSet):
    queryset = SupplierInvoice.objects.select_related("supplier", "purchase_order")
    serializer_class = SupplierInvoiceSerializer

    def get_permissions(self):
        permission = (
            "pharmacy.procurement_manage"
            if self.action not in {"list", "retrieve"}
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        invoice = self.get_object()
        po = invoice.purchase_order
        ordered = sum((i.quantity_ordered * i.unit_price for i in po.items.all()), Decimal("0"))
        received = sum((i.quantity_received * i.unit_price for i in po.items.all()), Decimal("0"))
        tolerance = Decimal("0.01")
        discrepancies = []
        if abs(ordered - invoice.total_amount) > tolerance:
            discrepancies.append(
                {"field": "total", "ordered": str(ordered), "invoiced": str(invoice.total_amount)}
            )
        if received < invoice.total_amount - tolerance:
            discrepancies.append(
                {
                    "field": "receipt",
                    "received": str(received),
                    "invoiced": str(invoice.total_amount),
                }
            )
        state = "mismatch" if discrepancies else "matched"
        match, _ = ThreeWayMatch.objects.update_or_create(
            invoice=invoice,
            defaults={
                "purchase_order": po,
                "ordered_total": ordered,
                "received_total": received,
                "invoiced_total": invoice.total_amount,
                "status": state,
                "discrepancies": discrepancies,
            },
        )
        invoice.status = state
        invoice.save(update_fields=["status"])
        log_audit(
            request,
            "three_way_match",
            "SupplierInvoice",
            invoice.id,
            new_data={"status": state, "discrepancies": discrepancies},
        )
        return Response(ThreeWayMatchSerializer(match).data)


class StockReceiptViewSet(viewsets.ModelViewSet):
    queryset = StockReceipt.objects.select_related(
        "purchase_order", "invoice", "received_by", "approved_by"
    ).prefetch_related("lines__purchase_item")
    serializer_class = StockReceiptSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_permissions(self):
        permission = (
            "pharmacy.stock_manage"
            if self.action in ("create", "approve", "reject", "return_receipt")
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    def perform_create(self, serializer):
        serializer.save(received_by=self.request.user)

    @action(detail=True, methods=("post",))
    @transaction.atomic
    def approve(self, request, pk=None):
        receipt = StockReceipt.objects.select_for_update().get(pk=self.get_object().pk)
        if receipt.status != StockReceipt.Status.PENDING:
            return Response({"detail": "Recebimento já processado."}, status=400)
        lines = list(
            receipt.lines.select_related(
                "purchase_item__drug", "purchase_item__material"
            ).select_for_update(of=("self",))
        )
        for line in lines:
            item = line.purchase_item
            if line.quantity <= 0 or line.quantity > item.quantity_ordered - item.quantity_received:
                return Response({"detail": "Quantidade recebida inválida."}, status=400)
            if (
                item.drug
                and item.drug.is_controlled
                and line.controlled_witness_id != request.user.id
            ):
                return Response(
                    {"detail": "Controlado exige dupla conferência por testemunha."}, status=400
                )
            lookup = {"drug": item.drug} if item.drug_id else {"material": item.material}
            stock_item, _ = StockItem.objects.get_or_create(
                **lookup,
                lot_number=line.lot_number or f"RC-{str(receipt.id)[:8]}",
                expiry_date=line.expiry_date,
                defaults={"quantity": Decimal("0")},
            )
            StockMovement.objects.create(
                stock_item=stock_item,
                movement_type="entry",
                quantity=line.quantity,
                reference=str(receipt.id),
                notes="Entrada conferida",
                performed_by=request.user,
            )
            line.stock_item = stock_item
            line.save(update_fields=("stock_item",))
            item.quantity_received = item.quantity_received + line.quantity
            item.save(update_fields=("quantity_received",))
        receipt.status = StockReceipt.Status.APPROVED
        receipt.approved_by = request.user
        receipt.approved_at = timezone.now()
        receipt.save(update_fields=("status", "approved_by", "approved_at"))
        log_audit(
            request,
            "approve_stock_receipt",
            "StockReceipt",
            receipt.id,
            new_data={"status": StockReceipt.Status.APPROVED},
        )
        return Response(self.get_serializer(receipt).data)

    @action(detail=True, methods=("post",))
    @transaction.atomic
    def reject(self, request, pk=None):
        receipt = StockReceipt.objects.select_for_update().get(pk=self.get_object().pk)
        if receipt.status != StockReceipt.Status.PENDING:
            return Response({"detail": "Recebimento já processado."}, status=400)
        receipt.status = StockReceipt.Status.REJECTED
        receipt.notes = request.data.get("notes", receipt.notes)
        receipt.save(update_fields=("status", "notes"))
        log_audit(
            request,
            "reject_stock_receipt",
            "StockReceipt",
            receipt.id,
            new_data={"status": StockReceipt.Status.REJECTED},
        )
        return Response(self.get_serializer(receipt).data)

    @action(detail=True, methods=("post",), url_path="return")
    @transaction.atomic
    def return_receipt(self, request, pk=None):
        receipt = StockReceipt.objects.select_for_update().get(pk=self.get_object().pk)
        if receipt.status != StockReceipt.Status.APPROVED:
            return Response(
                {"detail": "Somente recebimentos efetivados podem ser devolvidos."}, status=400
            )
        try:
            # Whole devolução is atomic: if any negative movement would drive stock
            # below zero, StockMovement.save() raises ValueError and the entire
            # transaction rolls back — the receipt stays consistently APPROVED.
            with transaction.atomic():
                for line in receipt.lines.select_related(
                    "stock_item", "purchase_item"
                ).select_for_update(of=("self",)):
                    if line.stock_item_id:
                        StockMovement.objects.create(
                            stock_item=line.stock_item,
                            movement_type="return",
                            quantity=-line.quantity,
                            reference=str(receipt.id),
                            notes="Devolução de recebimento",
                            performed_by=request.user,
                        )
                    # Restore the PO line's received quantity that approve() added.
                    item = line.purchase_item
                    item.quantity_received = item.quantity_received - line.quantity
                    item.save(update_fields=("quantity_received",))
                receipt.status = StockReceipt.Status.RETURNED
                receipt.notes = request.data.get("notes", receipt.notes)
                receipt.save(update_fields=("status", "notes"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        log_audit(
            request,
            "return_stock_receipt",
            "StockReceipt",
            receipt.id,
            new_data={"status": StockReceipt.Status.RETURNED},
        )
        return Response(self.get_serializer(receipt).data)


class ThreeWayMatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ThreeWayMatch.objects.select_related("invoice", "purchase_order")
    serializer_class = ThreeWayMatchSerializer

    def get_permissions(self):
        permission = "pharmacy.procurement_manage" if self.action == "approve" else "pharmacy.read"
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        match = self.get_object()
        if match.status == "mismatch" and not str(request.data.get("override_reason", "")).strip():
            return Response(
                {"detail": "Justificativa obrigatória para aprovar divergência."}, status=400
            )
        match.status = "approved"
        match.override_reason = str(request.data.get("override_reason", "")).strip()
        match.reviewed_by = request.user
        match.reviewed_at = timezone.now()
        match.save(update_fields=["status", "override_reason", "reviewed_by", "reviewed_at"])
        match.invoice.status = "approved"
        match.invoice.save(update_fields=["status"])
        log_audit(
            request,
            "approve_three_way_match",
            "ThreeWayMatch",
            match.id,
            new_data={"status": "approved", "override_reason": match.override_reason},
        )
        return Response(ThreeWayMatchSerializer(match).data)


class PharmacistValidationViewSet(viewsets.ModelViewSet):
    queryset = PharmacistValidation.objects.select_related("prescription", "pharmacist")
    serializer_class = PharmacistValidationSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_permissions(self):
        permission = (
            "pharmacy.clinical_validate"
            if self.action != "list" and self.action != "retrieve"
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    def perform_create(self, serializer):
        validation = serializer.save()
        log_audit(
            self.request, "pharmacist_validation_create", "PharmacistValidation", validation.id
        )

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        allowed = {choice for choice, _ in PharmacistValidation.Status.choices} - {
            PharmacistValidation.Status.PENDING
        }
        decision = request.data.get("status")
        notes = request.data.get("clinical_notes", "").strip()
        if decision not in allowed:
            return Response({"status": "Decisão inválida."}, status=400)
        if decision != PharmacistValidation.Status.APPROVED and not notes:
            return Response({"clinical_notes": "Justificativa obrigatória."}, status=400)
        with transaction.atomic():
            validation = PharmacistValidation.objects.select_for_update().get(
                pk=self.get_object().pk
            )
            if validation.status != PharmacistValidation.Status.PENDING:
                return Response({"detail": "Validação já decidida."}, status=409)
            validation.status = decision
            validation.clinical_notes = notes
            validation.pharmacist = request.user
            validation.validated_at = timezone.now()
            validation.save(
                update_fields=[
                    "status",
                    "clinical_notes",
                    "pharmacist",
                    "validated_at",
                    "updated_at",
                ]
            )
        log_audit(
            request,
            "pharmacist_validation_decide",
            "PharmacistValidation",
            validation.id,
            new_data={"status": decision},
        )
        return Response(self.get_serializer(validation).data)


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer

    def get_permissions(self):
        permission = (
            "pharmacy.warehouse_manage"
            if self.action != "list" and self.action != "retrieve"
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]


class StorageLocationViewSet(viewsets.ModelViewSet):
    queryset = StorageLocation.objects.select_related("warehouse")
    serializer_class = StorageLocationSerializer

    def get_permissions(self):
        permission = (
            "pharmacy.warehouse_manage"
            if self.action != "list" and self.action != "retrieve"
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]


class InventoryCountViewSet(viewsets.ModelViewSet):
    queryset = InventoryCount.objects.prefetch_related("lines")
    serializer_class = InventoryCountSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_permissions(self):
        permission = (
            "pharmacy.inventory_count"
            if self.action in ("create", "submit")
            else "pharmacy.inventory_approve"
            if self.action == "decide"
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    @action(detail=True, methods=("post",))
    def submit(self, request, pk=None):
        row = InventoryService.submit(self.get_object(), request.user)
        return Response(self.get_serializer(row).data)

    @action(detail=True, methods=("post",))
    def decide(self, request, pk=None):
        row = InventoryService.decide(
            self.get_object(),
            request.user,
            bool(request.data.get("approve")),
            request.data.get("note", ""),
        )
        return Response(self.get_serializer(row).data)


class StockTransferViewSet(viewsets.ModelViewSet):
    queryset = StockTransfer.objects.prefetch_related("lines")
    serializer_class = StockTransferSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_permissions(self):
        permission = (
            "pharmacy.transfer_accept"
            if self.action == "accept"
            else "pharmacy.transfer_manage"
            if self.action in ("create", "ship")
            else "pharmacy.read"
        )
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    @action(detail=True, methods=("post",))
    def ship(self, request, pk=None):
        return Response(
            self.get_serializer(TransferService.ship(self.get_object(), request.user)).data
        )

    @action(detail=True, methods=("post",))
    def accept(self, request, pk=None):
        return Response(
            self.get_serializer(TransferService.accept(self.get_object(), request.user)).data
        )


class LotRecallViewSet(viewsets.ModelViewSet):
    queryset = LotRecall.objects.all()
    serializer_class = LotRecallSerializer
    http_method_names = ("get", "post", "head", "options")

    def get_permissions(self):
        permission = "pharmacy.recall_manage" if self.action == "create" else "pharmacy.read"
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission(permission)]

    @transaction.atomic
    def perform_create(self, serializer):
        recall = serializer.save(created_by=self.request.user)
        lots = StockItem.objects.filter(
            lot_number=recall.lot_number, drug=recall.drug, material=recall.material
        ).select_for_update()
        lots.update(status="recalled")
        log_audit(
            self.request,
            "recall",
            "LotRecall",
            recall.id,
            new_data={"lot_number": recall.lot_number},
        )


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=old_data,
        new_data=new_data,
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


# ─── S-026: Catalog ───────────────────────────────────────────────────────────


class DrugViewSet(viewsets.ModelViewSet):
    serializer_class = DrugSerializer

    def get_queryset(self):
        qs = Drug.objects.all()
        search = self.request.query_params.get("search")
        if search:
            from django.db.models import Q

            # pg_trgm fuzzy search via LIKE (trigram index picks this up)
            qs = qs.filter(Q(name__icontains=search) | Q(generic_name__icontains=search))
        controlled = self.request.query_params.get("controlled")
        if controlled == "true":
            qs = qs.exclude(controlled_class="none")
        active = self.request.query_params.get("active")
        if active == "false":
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.catalog_manage")]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def perform_create(self, serializer):
        drug = serializer.save()
        log_audit(self.request, "create", "Drug", drug.id, new_data=serializer.data)

    def perform_update(self, serializer):
        old = DrugSerializer(serializer.instance).data
        drug = serializer.save()
        log_audit(
            self.request,
            "update",
            "Drug",
            drug.id,
            old_data=old,
            new_data=DrugSerializer(drug).data,
        )

    def perform_destroy(self, instance):
        old_data = DrugSerializer(instance).data
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        log_audit(self.request, "delete", "Drug", instance.id, old_data=old_data)


class MaterialViewSet(viewsets.ModelViewSet):
    serializer_class = MaterialSerializer

    def get_queryset(self):
        qs = Material.objects.all()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        active = self.request.query_params.get("active")
        if active == "false":
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.catalog_manage")]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def perform_create(self, serializer):
        material = serializer.save()
        log_audit(self.request, "create", "Material", material.id, new_data=serializer.data)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])


# ─── S-027: Stock ─────────────────────────────────────────────────────────────


class StockItemViewSet(viewsets.ModelViewSet):
    serializer_class = StockItemSerializer

    def get_queryset(self):
        qs = StockItem.objects.select_related("drug", "material")
        drug_id = self.request.query_params.get("drug")
        if drug_id:
            qs = qs.filter(drug_id=drug_id)
        material_id = self.request.query_params.get("material")
        if material_id:
            qs = qs.filter(material_id=material_id)
        return qs

    def get_permissions(self):
        if self.action in ("quarantine", "release"):
            return [
                IsAuthenticated(),
                _PHARMACY_MODULE,
                HasPermission("pharmacy.quarantine_manage"),
            ]
        if self.action in ("create", "update", "partial_update", "destroy", "adjust"):
            return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.stock_manage")]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        return Response(
            {"detail": "Ajustes exigem contagem cega e aprovação em /pharmacy/inventory-counts/."},
            status=status.HTTP_409_CONFLICT,
        )

    @action(detail=True, methods=["post"])
    def quarantine(self, request, pk=None):
        item = self.get_object()
        item.status = "quarantine"
        item.save(update_fields=("status", "updated_at"))
        log_audit(
            request,
            "quarantine",
            "StockItem",
            item.id,
            new_data={"reason": request.data.get("reason", "")},
        )
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        item = self.get_object()
        if item.status != "quarantine":
            return Response(
                {"detail": "Somente lotes em quarentena podem ser liberados."}, status=409
            )
        item.status = "available"
        item.save(update_fields=("status", "updated_at"))
        log_audit(request, "release_quarantine", "StockItem", item.id)
        return Response(self.get_serializer(item).data)


class StockMovementViewSet(viewsets.ModelViewSet):
    serializer_class = StockMovementSerializer
    http_method_names = ["get", "post", "head", "options"]  # no PUT/PATCH/DELETE (append-only)

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.stock_manage")]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("stock_item", "performed_by")
        stock_item_id = self.request.query_params.get("stock_item")
        if stock_item_id:
            qs = qs.filter(stock_item_id=stock_item_id)
        return qs

    def perform_create(self, serializer):
        movement = serializer.save(performed_by=self.request.user)
        log_audit(
            self.request,
            "create",
            "StockMovement",
            movement.id,
            new_data={"type": movement.movement_type, "qty": str(movement.quantity)},
        )


class StockAlertsView(APIView):
    """GET /pharmacy/stock/alerts/ — returns cached expiry + low-stock alert lists from Redis."""

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def get(self, request):
        import json

        from django.conf import settings

        schema = getattr(request.tenant, "schema_name", "public")
        cache_available = True
        try:
            import redis

            r = redis.from_url(getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0"))
            expiry_raw = r.get(f"pharmacy:{schema}:expiry_alerts")
            min_stock_raw = r.get(f"pharmacy:{schema}:min_stock_alerts")
            expiry_items = json.loads(expiry_raw) if expiry_raw else []
            min_stock_items = json.loads(min_stock_raw) if min_stock_raw else []
        except Exception:
            expiry_items = []
            min_stock_items = []
            cache_available = False
        return Response(
            {
                "expiry_alerts": expiry_items,
                "min_stock_alerts": min_stock_items,
                "cache_available": cache_available,
            }
        )


class StockAvailabilityView(APIView):
    """GET /pharmacy/stock/availability/?drug=<uuid> — returns available lots."""

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def get(self, request):
        drug_id = request.query_params.get("drug")
        if not drug_id:
            return Response({"detail": "drug query param required."}, status=400)
        from django.db.models import Q

        today = timezone.now().date()
        lots = (
            StockItem.objects.filter(
                drug_id=drug_id,
                quantity__gt=0,
                status="available",
            )
            .filter(Q(expiry_date__gte=today) | Q(expiry_date__isnull=True))
            .order_by("expiry_date")
        )
        data = StockItemSerializer(lots, many=True).data
        return Response(
            {"available_lots": data, "total": sum(float(lot["quantity"]) for lot in data)}
        )


# ─── Stockout-prediction wedge S3: proactive risk surface ─────────────────────


def _serialize_stock_alert(alert: StockAlert) -> dict:
    """Serialize one persistent StockAlert for the supply-risk dashboard (S3).

    PROACTIVE ONLY — this is the predictive layer (StockAlert rows written by the
    deterministic StockoutService), kept entirely separate from the legacy
    Redis-cached StockAlertsView. The reorder suggestion is the value the engine
    persisted at eval time (sized from derived velocity + configured lead time +
    real balance — no invented supplier/contract data); it is only present for
    stockout_risk alerts.
    """
    target = alert.target
    return {
        "id": str(alert.id),
        "kind": alert.kind,
        "kind_display": alert.get_kind_display(),
        "drug": str(alert.drug_id) if alert.drug_id else None,
        "material": str(alert.material_id) if alert.material_id else None,
        "product_name": target.name if target is not None else "",
        "stock_item": str(alert.stock_item_id) if alert.stock_item_id else None,
        "predicted_date": (alert.predicted_date.isoformat() if alert.predicted_date else None),
        "days_to_stockout": (
            str(alert.days_to_stockout) if alert.days_to_stockout is not None else None
        ),
        "predicted_waste_qty": (
            str(alert.predicted_waste_qty) if alert.predicted_waste_qty is not None else None
        ),
        "suggested_reorder_qty": (
            str(alert.suggested_reorder_qty) if alert.suggested_reorder_qty is not None else None
        ),
        "message": alert.message,
        "severity": alert.severity,
        "status": alert.status,
        "created_at": alert.created_at.isoformat(),
    }


class StockRiskView(APIView):
    """GET /pharmacy/stock/risk/ — the PROACTIVE predictive supply-risk surface.

    Lists OPEN ``StockAlert`` rows produced by the deterministic StockoutService
    (stockout_risk + expiry_waste), with a reorder suggestion per stockout_risk
    alert. This is a NEW endpoint, deliberately separate from the legacy
    Redis-cached ``StockAlertsView`` (which we do not touch).

    Respects the ``stockout_safety`` feature flag: when OFF the list is EMPTY
    (the engine never ran, and the gestor should not see stale predictions).
    Optional ``?kind=stockout_risk|expiry_waste`` filter. Read-only; advise only —
    there is NO dispense-time gate anywhere in this wedge.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def get(self, request):
        from apps.pharmacy.services.stockout_safety import StockoutService

        if not StockoutService.is_enabled():
            return Response({"alerts": [], "stockout_safety_enabled": False})

        qs = (
            StockAlert.objects.filter(status=StockAlert.Status.OPEN)
            .select_related("drug", "material")
            .order_by("predicted_date", "-created_at")
        )
        kind = request.query_params.get("kind")
        if kind in (StockAlert.Kind.STOCKOUT_RISK, StockAlert.Kind.EXPIRY_WASTE):
            qs = qs.filter(kind=kind)

        alerts = [_serialize_stock_alert(a) for a in qs]
        return Response({"alerts": alerts, "stockout_safety_enabled": True})


class AcknowledgeStockAlertView(APIView):
    """POST /pharmacy/stock-alerts/<uuid:alert_id>/acknowledge/

    Body: {note?: str}

    Mirrors billing.AcknowledgeGlosaAlertView. Sets status=acknowledged,
    acknowledged_by, acknowledged_at (+ optional note). NO minimum-length rule:
    StockAlerts are advise-only (no block path), so a justification is optional.
    The acknowledged alert leaves the OPEN risk list. Same pharmacy.read /
    module permission as the risk surface.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def post(self, request, alert_id):
        note = (request.data.get("note") or "").strip()
        try:
            alert = StockAlert.objects.get(id=alert_id)
        except StockAlert.DoesNotExist:
            return Response(
                {"detail": "Alerta de estoque não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only an open alert is actionable; re-acking would overwrite the original
        # acknowledged_by/at and emit audit noise.
        if alert.status != StockAlert.Status.OPEN:
            return Response(
                {"detail": "Alerta já reconhecido ou resolvido; nada a fazer."},
                status=status.HTTP_409_CONFLICT,
            )

        alert.acknowledge(request.user, note)
        log_audit(
            request,
            "stock_alert_acknowledged",
            "stock_alert",
            alert.id,
            new_data={"note": note, "kind": alert.kind},
        )
        return Response(
            {
                "message": "Alerta reconhecido com sucesso.",
                "alert_id": str(alert.id),
                "status": alert.status,
                "acknowledged_at": alert.acknowledged_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


# ─── S-028: Dispensation ──────────────────────────────────────────────────────


class DispensationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DispensationSerializer

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.dispense")]

    def get_queryset(self):
        qs = Dispensation.objects.select_related(
            "prescription", "prescription_item", "patient", "dispensed_by"
        ).prefetch_related("lots__stock_item__drug", "lots__stock_item__material")
        patient_id = self.request.query_params.get("patient")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        prescription_id = self.request.query_params.get("prescription")
        if prescription_id:
            qs = qs.filter(prescription_id=prescription_id)
        return qs


class DispenseView(APIView):
    """
    POST /pharmacy/dispense/
    Atomic FEFO dispensation across multiple lots.
    Requires signed Rx, checks controlled-substance role gate.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.dispense")]

    def post(self, request):
        serializer = DispenseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from apps.emr.models import PrescriptionItem

        try:
            rx_item = PrescriptionItem.objects.select_related(
                "prescription", "drug", "prescription__patient"
            ).get(pk=data["prescription_item_id"])
        except PrescriptionItem.DoesNotExist:
            return Response({"detail": "PrescriptionItem not found."}, status=404)

        prescription = rx_item.prescription
        drug = rx_item.drug

        # Gate 1: prescription must be signed and not cancelled/dispensed
        if prescription.status not in ("signed", "partially_dispensed"):
            return Response(
                {"detail": "Receita inválida. Só receitas assinadas podem ser dispensadas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Gate 2: controlled substance requires dispense_controlled permission
        # Superuser bypass intentionally removed — ANVISA requires a named pharmacist record
        # for all controlled-substance dispensations regardless of account privilege.
        if drug.is_controlled:
            role = request.user.effective_role()
            perms = role.permissions if role else []
            if "pharmacy.dispense_controlled" not in perms:
                return Response(
                    {"detail": "Permissão insuficiente para dispensar medicamento controlado."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Gate 3: controlled substances require notes
        if drug.is_controlled and not data.get("notes", "").strip():
            return Response(
                {"detail": "Notas obrigatórias para dispensação de medicamento controlado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Gate 4: prescription-safety soft-stop (dose wedge PR B + allergy wedge
        # PR A1). Re-evaluate at the pharmacy gate so a dose/weight/allergy changed
        # AFTER signing is caught here too. No-op when both flags are OFF for this
        # tenant. A re-check inside the dispense transaction guards against a race
        # with acknowledge.
        from apps.emr.services.allergy_safety import AllergySafetyService
        from apps.emr.services.dose_safety import DoseCheckService
        from apps.emr.services.prescription_safety_gate import (
            build_block_payload,
            has_blocking_safety_alert,
        )

        with transaction.atomic():
            locked_rx = (
                prescription.__class__.objects.select_for_update()
                .filter(pk=prescription.pk)
                .first()
            )
            DoseCheckService(requesting_user=request.user).evaluate_prescription(
                locked_rx, gate="dispense"
            )
            AllergySafetyService(requesting_user=request.user).evaluate_prescription(
                locked_rx, gate="dispense"
            )
            if has_blocking_safety_alert(locked_rx):
                return Response(
                    build_block_payload(locked_rx),
                    status=status.HTTP_409_CONFLICT,
                )

        requested_qty = Decimal(str(data["quantity"]))
        today = timezone.now().date()

        try:
            dispensation = self._dispense_fefo(
                request, prescription, rx_item, drug, requested_qty, data.get("notes", ""), today
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_audit(
            request,
            "dispense",
            "Dispensation",
            dispensation.id,
            new_data={
                "prescription_item": str(rx_item.id),
                "drug": drug.name,
                "quantity": str(requested_qty),
            },
        )
        return Response(DispensationSerializer(dispensation).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _dispense_fefo(self, request, prescription, rx_item, drug, requested_qty, notes, today):
        """
        FEFO: lock lots in expiry order, allocate greedily, raise ValueError if insufficient.
        The select_for_update + re-check inside the lock prevents negative stock.
        PrescriptionItem is also locked to prevent concurrent over-dispense.
        """
        from django.db.models import Q as _Q
        from django.db.models import Sum

        from apps.emr.models import PrescriptionItem

        # Lock the PrescriptionItem row first to prevent concurrent over-dispense.
        # Without this lock, two requests read already_dispensed=0 simultaneously
        # and both proceed to dispense the full quantity.
        rx_item = PrescriptionItem.objects.select_for_update().get(pk=rx_item.pk)

        lots = (
            StockItem.objects.select_for_update(of=("self",))
            .filter(
                drug=drug,
                status="available",
            )
            .filter(_Q(expiry_date__gte=today) | _Q(expiry_date__isnull=True))
            .order_by("expiry_date")
        )

        # Guard: check already-dispensed quantity against prescribed quantity (inside lock)
        already_dispensed = DispensationLot.objects.filter(
            dispensation__prescription_item=rx_item
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        remaining_prescribed = rx_item.quantity - already_dispensed
        if requested_qty > remaining_prescribed:
            raise ValueError(
                f"Quantidade solicitada ({requested_qty}) excede o saldo da receita "
                f"({remaining_prescribed}). Já dispensado: {already_dispensed}."
            )

        # Re-check quantities after acquiring lock
        available = [(lot, lot.quantity) for lot in lots if lot.quantity > Decimal("0")]
        total_available = sum(q for _, q in available)

        if total_available < requested_qty:
            raise ValueError(
                f"Estoque insuficiente. Disponível: {total_available}, Solicitado: {requested_qty}"
            )

        dispensation = Dispensation.objects.create(
            prescription=prescription,
            prescription_item=rx_item,
            patient=prescription.patient,
            dispensed_by=request.user,
            notes=notes,
        )

        remaining = requested_qty
        for lot, available_qty in available:
            if remaining <= Decimal("0"):
                break
            take = min(available_qty, remaining)
            DispensationLot.objects.create(
                dispensation=dispensation,
                stock_item=lot,
                quantity=take,
            )
            # StockMovement.save() does the F()-based atomic decrement
            StockMovement.objects.create(
                stock_item=lot,
                movement_type="dispense",
                quantity=-take,
                reference=str(dispensation.id),
                notes=f"Dispensação {dispensation.id}",
                performed_by=request.user,
            )
            remaining -= take

        # Update Prescription.status inside the lock so reporting sees correct state.
        # Recompute total dispensed across ALL items on this Rx to determine new status.
        from apps.emr.models import Prescription as _Rx

        rx_locked = _Rx.objects.select_for_update().get(pk=prescription.pk)
        all_items = rx_locked.items.all()
        all_fully_dispensed = all(
            (
                DispensationLot.objects.filter(dispensation__prescription_item=item).aggregate(
                    total=Sum("quantity")
                )["total"]
                or Decimal("0")
            )
            >= item.quantity
            for item in all_items
        )
        if all_fully_dispensed:
            rx_locked.status = "dispensed"
        else:
            rx_locked.status = "partially_dispensed"
        rx_locked.save(update_fields=["status"])

        return dispensation


# ─── S-042: Purchase Orders ───────────────────────────────────────────────────


class SupplierViewSet(viewsets.ModelViewSet):
    """CRUD for suppliers. Requires pharmacy.stock_manage."""

    serializer_class = SupplierSerializer

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.stock_manage")]

    def get_queryset(self):
        qs = Supplier.objects.all()
        active = self.request.query_params.get("active")
        if active == "false":
            qs = qs.filter(is_active=False)
        else:
            qs = qs.filter(is_active=True)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """CRUD + receive action for purchase orders."""

    serializer_class = PurchaseOrderSerializer

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.stock_manage")]

    def get_queryset(self):
        from django.db.models import Count

        qs = (
            PurchaseOrder.objects.select_related("supplier", "created_by")
            .prefetch_related("items")
            .annotate(item_count=Count("items"))
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        supplier_id = self.request.query_params.get("supplier")
        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="receive")
    @transaction.atomic
    def receive(self, request, pk=None):
        """
        POST /pharmacy/purchase-orders/{id}/receive/
        Receives items from the PO: creates StockMovements and updates stock quantities.
        Atomic — if any item fails, the whole operation rolls back.
        """
        try:
            po = PurchaseOrder.objects.select_for_update().get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Pedido de compra não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        if po.status == PurchaseOrder.Status.CANCELLED:
            return Response(
                {"detail": "Não é possível receber um pedido cancelado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if po.status == PurchaseOrder.Status.RECEIVED:
            return Response(
                {"detail": "Pedido já foi totalmente recebido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = POReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        receive_items = serializer.validated_data["items"]
        lot_prefix = f"PO-{str(po.id)[:8]}"
        movements_created = []

        # Fetch all requested items in one locked query; validate before mutating.
        item_ids = [recv["item_id"] for recv in receive_items]
        items_by_id = {
            str(item.pk): item
            for item in PurchaseOrderItem.objects.select_related("drug", "material")
            .select_for_update(of=("self",))
            .filter(pk__in=item_ids, po=po)
        }
        missing = [str(rid) for rid in item_ids if str(rid) not in items_by_id]
        if missing:
            return Response(
                {"detail": f"Item(s) não encontrado(s) neste pedido: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for recv in receive_items:
            item = items_by_id[str(recv["item_id"])]
            delta = recv["quantity_received"]
            lot_number = recv.get("lot_number") or lot_prefix
            expiry_date = recv.get("expiry_date")

            # get_or_create is safe: UniqueConstraint(nulls_distinct=False) prevents duplicate
            # (drug/material, lot_number, expiry_date) rows even when expiry_date is NULL.
            item_lookup = {"drug": item.drug} if item.drug else {"material": item.material}
            stock_item, _ = StockItem.objects.get_or_create(
                **item_lookup,
                lot_number=lot_number,
                expiry_date=expiry_date,
                defaults={"quantity": Decimal("0")},
            )

            movement = StockMovement.objects.create(
                stock_item=stock_item,
                movement_type="purchase_order_receiving",
                quantity=delta,
                reference=lot_prefix,
                notes=f"Recebimento de pedido de compra #{lot_prefix}",
                performed_by=request.user,
            )
            movements_created.append(movement)

            item.quantity_received += delta
            item.save(update_fields=["quantity_received"])

        # Update PO status
        all_items = po.items.all()
        all_received = all(item.quantity_received >= item.quantity_ordered for item in all_items)
        po.status = PurchaseOrder.Status.RECEIVED if all_received else PurchaseOrder.Status.PARTIAL
        po.save(update_fields=["status", "updated_at"])

        # Re-fetch with prefetch so the serializer doesn't trigger additional queries.
        from django.db.models import Count

        po = (
            PurchaseOrder.objects.prefetch_related("items__drug", "items__material")
            .annotate(item_count=Count("items"))
            .get(pk=po.pk)
        )
        return Response(
            PurchaseOrderSerializer(po).data,
            status=status.HTTP_200_OK,
        )


# ─── S29-02: DoseRule Curation endpoint ──────────────────────────────────────


class DoseRuleViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only list of DoseRule entries with a pharmacist-only `validate` action.

    INVIOLABLE: `validated` is NEVER writable through this viewset's serializer.
    The ONLY mutation path is through the `validate` action below.
    """

    serializer_class = DoseRuleSerializer

    def get_queryset(self):
        qs = DoseRule.objects.select_related("formulary__drug", "validated_by")
        validated = self.request.query_params.get("validated")
        if validated == "true":
            qs = qs.filter(validated=True)
        elif validated == "false":
            qs = qs.filter(validated=False)
        return qs

    def get_permissions(self):
        if self.action == "validate":
            return [
                IsAuthenticated(),
                _PHARMACY_MODULE,
                HasPermission("pharmacy.catalog_manage"),
            ]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    @action(detail=True, methods=["post"], url_path="validate")
    def validate(self, request, pk=None):
        """POST /pharmacy/dose-rules/{id}/validate/ — pharmacist sign-off on a DoseRule.

        Sets validated=True, validated_by=request.user, validated_at=now() and
        writes an AuditLog row with action="dose_rule_validated". Returns 409 if
        the rule is already validated.
        """
        rule = self.get_object()

        if rule.validated:
            return Response(
                {"detail": "Esta regra já foi validada."},
                status=status.HTTP_409_CONFLICT,
            )

        rule.validated = True
        rule.validated_by = request.user
        rule.validated_at = timezone.now()
        rule.save(update_fields=["validated", "validated_by", "validated_at"])

        log_audit(
            request,
            "dose_rule_validated",
            "DoseRule",
            rule.id,
            new_data={"validated_by": request.user.email},
        )

        return Response(self.get_serializer(rule).data)


# ─── S29-03: AllergenClass & DrugInteraction Curation endpoints ───────────────


class AllergenClassViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only list of AllergenClass entries with a pharmacist-only `set-active` action.

    INVIOLABLE: `active` is NEVER writable through this viewset's serializer.
    The ONLY mutation path is through the `set_active` action below.
    """

    serializer_class = AllergenClassSerializer
    queryset = AllergenClass.objects.all()

    def get_permissions(self):
        if self.action == "set_active":
            return [
                IsAuthenticated(),
                _PHARMACY_MODULE,
                HasPermission("pharmacy.catalog_manage"),
            ]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """POST /pharmacy/allergen-classes/{id}/set-active/ — toggle active flag.

        Body: {"active": bool}. Returns 400 if key is missing.
        Writes AuditLog with action="allergen_class_set_active".
        """
        if "active" not in request.data:
            return Response(
                {"detail": "'active' key is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(request.data["active"], bool):
            return Response(
                {"detail": "'active' deve ser um booleano JSON (true ou false)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj = self.get_object()
        obj.active = request.data["active"]
        obj.save(update_fields=["active"])

        log_audit(
            request,
            "allergen_class_set_active",
            "AllergenClass",
            obj.id,
            new_data={"active": obj.active},
        )

        return Response(self.get_serializer(obj).data)


class DrugInteractionViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only list of DrugInteraction entries with a pharmacist-only `set-active` action.

    INVIOLABLE: `active` is NEVER writable through this viewset's serializer.
    The ONLY mutation path is through the `set_active` action below.
    """

    serializer_class = DrugInteractionSerializer
    queryset = DrugInteraction.objects.all()

    def get_permissions(self):
        if self.action == "set_active":
            return [
                IsAuthenticated(),
                _PHARMACY_MODULE,
                HasPermission("pharmacy.catalog_manage"),
            ]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """POST /pharmacy/drug-interactions/{id}/set-active/ — toggle active flag.

        Body: {"active": bool}. Returns 400 if key is missing.
        Writes AuditLog with action="drug_interaction_set_active".
        """
        if "active" not in request.data:
            return Response(
                {"detail": "'active' key is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(request.data["active"], bool):
            return Response(
                {"detail": "'active' deve ser um booleano JSON (true ou false)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj = self.get_object()
        obj.active = request.data["active"]
        obj.save(update_fields=["active"])

        log_audit(
            request,
            "drug_interaction_set_active",
            "DrugInteraction",
            obj.id,
            new_data={"active": obj.active},
        )

        return Response(self.get_serializer(obj).data)


# ─── S29-05: Curation Readiness dashboard ────────────────────────────────────


class CurationReadinessView(APIView):
    """GET /pharmacy/curation/readiness/ — per-wedge data-readiness shape.

    Returns a fully-derived readiness summary for the S29-05 dashboard.
    Frontend does ZERO math — all counts and strings are computed here.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def get(self, request):
        # ── Dose wedge ────────────────────────────────────────────────────────
        dose_total = DoseRule.objects.filter(active=True).count()
        dose_ready = DoseRule.objects.filter(active=True, validated=True).count()
        if dose_total == 0:
            dose_blockers = []
            dose_text = "Nenhuma regra de dose cadastrada."
        elif dose_ready == dose_total:
            dose_blockers = []
            dose_text = f"Todas as {dose_total} regras de dose estão validadas."
        else:
            pending = dose_total - dose_ready
            dose_blockers = [f"{pending} regra(s) de dose aguardando validação"]
            dose_text = ""

        # ── Allergy wedge ─────────────────────────────────────────────────────
        allergy_total = AllergenClass.objects.count()
        allergy_ready = AllergenClass.objects.filter(active=True).count()
        if allergy_total == 0:
            allergy_blockers = []
            allergy_text = "Nenhuma classe de alérgenos cadastrada."
        elif allergy_ready == allergy_total:
            allergy_blockers = []
            allergy_text = f"Todas as {allergy_total} classes de alérgenos estão ativas."
        else:
            inactive = allergy_total - allergy_ready
            allergy_blockers = [f"{inactive} classe(s) de alérgenos inativa(s)"]
            allergy_text = ""

        # ── Interaction wedge ─────────────────────────────────────────────────
        interaction_total = DrugInteraction.objects.count()
        interaction_ready = DrugInteraction.objects.filter(active=True).count()
        if interaction_total == 0:
            interaction_blockers = []
            interaction_text = "Nenhuma interação medicamentosa cadastrada."
        elif interaction_ready == interaction_total:
            interaction_blockers = []
            interaction_text = f"Todas as {interaction_total} interações estão ativas."
        else:
            inactive_i = interaction_total - interaction_ready
            interaction_blockers = [f"{inactive_i} interação(ões) inativa(s)"]
            interaction_text = ""

        # ── Supply wedge ──────────────────────────────────────────────────────
        drug_total = Drug.objects.filter(is_active=True).count()
        material_total = Material.objects.filter(is_active=True).count()
        supply_total = drug_total + material_total

        drug_ready = Drug.objects.filter(is_active=True, reorder_point__isnull=False).count()
        material_ready = Material.objects.filter(
            is_active=True, reorder_point__isnull=False
        ).count()
        supply_ready = drug_ready + material_ready

        if supply_total == 0:
            supply_blockers = []
            supply_text = "Nenhum item de suprimento cadastrado."
        elif supply_ready == supply_total:
            supply_blockers = []
            supply_text = f"Todos os {supply_total} itens têm parâmetros de suprimento."
        else:
            unconfigured = supply_total - supply_ready
            supply_blockers = [f"{unconfigured} item(ns) sem ponto de reposição configurado"]
            supply_text = ""

        wedges = [
            {
                "key": "dose",
                "label": "Doses (formulário)",
                "total": dose_total,
                "ready_count": dose_ready,
                "blockers": dose_blockers,
                "ready_text": dose_text,
            },
            {
                "key": "allergy",
                "label": "Reatividade cruzada",
                "total": allergy_total,
                "ready_count": allergy_ready,
                "blockers": allergy_blockers,
                "ready_text": allergy_text,
            },
            {
                "key": "interaction",
                "label": "Interações medicamentosas",
                "total": interaction_total,
                "ready_count": interaction_ready,
                "blockers": interaction_blockers,
                "ready_text": interaction_text,
            },
            {
                "key": "supply",
                "label": "Suprimentos",
                "total": supply_total,
                "ready_count": supply_ready,
                "blockers": supply_blockers,
                "ready_text": supply_text,
            },
        ]
        return Response({"wedges": wedges})


# ─── Controlled-diversion wedge PR C3: compliance surface ─────────────────────

_CONTROLLED_ALERT_LIST_LIMIT = 200


def _serialize_controlled_alert(alert) -> dict:
    """Plain dict for a ControlledAlert + dispensation/patient context."""
    return {
        "id": str(alert.id),
        "dispensation_id": str(alert.dispensation_id),
        "patient_id": str(alert.patient_id),
        "patient_name": alert.patient.full_name,
        "drug": alert.drug.name,
        "drug_id": str(alert.drug_id),
        "controlled_class": alert.drug.controlled_class,
        "signal_kind": alert.signal_kind,
        "signal_kind_display": alert.get_signal_kind_display(),
        "severity": alert.severity,
        "detail": alert.detail,
        "status": alert.status,
        "engine_version": alert.engine_version,
        "acknowledged_by": str(alert.acknowledged_by_id) if alert.acknowledged_by_id else None,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "note": alert.note,
        "created_at": alert.created_at.isoformat(),
    }


class ControlledAlertsView(APIView):
    """GET /pharmacy/controlled/alerts/ — the controlled-diversion compliance surface.

    Lists OPEN ``ControlledAlert`` rows (newest first, capped) for pharmacist /
    compliance review — refill-too-soon, doctor-shopping, quantity-escalation.
    Respects the ``controlled_safety`` flag: EMPTY when OFF (the monitor never
    ran). Read-only; ADVISE only — nothing here blocked any dispensation.
    Optional ``?signal_kind=`` filter.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def get(self, request):
        from apps.pharmacy.services.controlled_safety import ControlledSafetyService

        if not ControlledSafetyService.is_enabled():
            return Response({"alerts": [], "controlled_safety_enabled": False})

        qs = (
            ControlledAlert.objects.filter(status=ControlledAlert.Status.OPEN)
            .select_related("patient", "drug", "dispensation")
            .order_by("-created_at")
        )
        signal_kind = request.query_params.get("signal_kind")
        if signal_kind in ControlledAlert.SignalKind.values:
            qs = qs.filter(signal_kind=signal_kind)

        total = qs.count()
        alerts = [_serialize_controlled_alert(a) for a in qs[:_CONTROLLED_ALERT_LIST_LIMIT]]
        return Response(
            {
                "alerts": alerts,
                "controlled_safety_enabled": True,
                "truncated": total > _CONTROLLED_ALERT_LIST_LIMIT,
            }
        )


class AcknowledgeControlledAlertView(APIView):
    """POST /pharmacy/controlled/alerts/<uuid:alert_id>/acknowledge/ — body {note?}.

    Flips an OPEN alert to ``acknowledged`` (compliance reviewed it). Re-acking a
    non-open alert → 409 (preserves the original ack). pharmacy.read floor (same
    as the stock-risk ack).
    """

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    def post(self, request, alert_id):
        note = (request.data.get("note") or "").strip()
        try:
            alert = ControlledAlert.objects.get(id=alert_id)
        except ControlledAlert.DoesNotExist:
            return Response({"detail": "Alerta não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if alert.status != ControlledAlert.Status.OPEN:
            return Response(
                {"detail": "Alerta já reconhecido ou resolvido; nada a fazer."},
                status=status.HTTP_409_CONFLICT,
            )

        alert.acknowledge(request.user, note)
        return Response(
            {
                "message": "Alerta reconhecido com sucesso.",
                "alert_id": str(alert.id),
                "acknowledged_at": alert.acknowledged_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


# ─── D-T1: Formulary CSV upload (pharmacist-facing) ───────────────────────────
#
# Two stateless endpoints behind the upload UI:
#   * preview/ — parse + validate + DRY-RUN upsert; returns the parsed rows and
#     what WOULD change. Writes nothing.
#   * commit/  — parse + validate + real upsert (idempotent); writes an AuditLog.
# Both require pharmacy.catalog_manage (admin / farmaceutico). Imported DoseRules
# land validated=False — the pharmacist still signs off each rule on the
# /formulario curation page, and only THEN is it safe to enable dose_safety.
#
# The flow is intentionally stateless: the client uploads the file once to
# preview, then re-uploads the SAME file to commit. No server-side temp storage.

# Cap on the uploaded CSV size (the curated high-alert formulary is tiny; this is
# a guard against a pathological upload, not a real-world limit).
_FORMULARY_UPLOAD_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB


def _read_uploaded_csv(request):
    """Return (content_str, error_response). Exactly one is non-None.

    Validates that a ``file`` part is present, under the size cap, and decodes as
    UTF-8. On any failure returns a ready-to-send 400 ``Response`` in the second
    slot so the caller can ``return`` it directly.
    """
    from apps.pharmacy.services.formulary_import import FormularyImportError, decode_csv

    upload = request.FILES.get("file")
    if upload is None:
        return None, Response(
            {"detail": "Envie um arquivo CSV no campo 'file'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if upload.size > _FORMULARY_UPLOAD_MAX_BYTES:
        return None, Response(
            {"detail": "Arquivo muito grande (máx. 5 MB)."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        content = decode_csv(upload.read())
    except FormularyImportError as exc:
        return None, Response(
            {"detail": exc.errors[0], "errors": exc.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return content, None


class FormularyUploadPreviewView(APIView):
    """POST /pharmacy/formulary/upload/preview/ — validate a CSV without writing.

    Body: multipart with a ``file`` part (the formulary CSV).
    Returns 200 ``{rows: [...], summary: {...}, errors: []}`` when valid, or 400
    ``{detail, errors: [...]}`` listing every line-numbered parse/validation
    error (no partial preview — it's all-or-nothing, mirroring the importer).
    """

    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.catalog_manage")]

    def post(self, request):
        from apps.pharmacy.services.formulary_import import (
            FormularyImportError,
            parse_and_validate,
            serialize_preview_row,
            write_rows,
        )

        content, error_response = _read_uploaded_csv(request)
        if error_response is not None:
            return error_response

        try:
            parsed_rows = parse_and_validate(content)
            summary = write_rows(parsed_rows, dry_run=True)
        except FormularyImportError as exc:
            return Response(
                {
                    "detail": (
                        f"{len(exc.errors)} erro(s) encontrado(s). "
                        "Corrija o arquivo e tente novamente — nada foi importado."
                    ),
                    "errors": exc.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "rows": [serialize_preview_row(r) for r in parsed_rows],
                "summary": summary.as_dict(),
                "errors": [],
            }
        )


class FormularyUploadCommitView(APIView):
    """POST /pharmacy/formulary/upload/commit/ — import a validated CSV.

    Body: multipart with a ``file`` part. Re-validates (the client may have
    edited between preview and commit), then upserts idempotently. Writes one
    AuditLog row (action="formulary_imported"). Returns 201 ``{summary, message}``.

    NOTE: imported DoseRules are ``validated=False``; they are inert until a
    pharmacist signs each off on the /formulario curation page. Only then is it
    safe to enable the ``dose_safety`` feature flag.
    """

    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.catalog_manage")]

    def post(self, request):
        from apps.pharmacy.services.formulary_import import (
            FormularyImportError,
            parse_and_validate,
            write_rows,
        )

        content, error_response = _read_uploaded_csv(request)
        if error_response is not None:
            return error_response

        try:
            parsed_rows = parse_and_validate(content)
            summary = write_rows(parsed_rows, dry_run=False)
        except FormularyImportError as exc:
            return Response(
                {
                    "detail": (f"{len(exc.errors)} erro(s) encontrado(s). Nada foi importado."),
                    "errors": exc.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        log_audit(
            request,
            "formulary_imported",
            "MedicationFormulary",
            "",
            # changed_rules carries per-rule before/after for every clinically
            # changed existing rule (forensics for the revalidation reset).
            new_data={**summary.as_dict(), "changed_rules": summary.changed_rules},
        )

        revalidation_note = (
            f" {summary.revalidation_required} regra(s) validada(s) tiveram valores "
            "clínicos alterados e voltaram a pendente de validação."
            if summary.revalidation_required
            else ""
        )
        return Response(
            {
                "message": (
                    f"Importação concluída: {summary.rules_created} regra(s) criada(s), "
                    f"{summary.rules_updated} atualizada(s)."
                    f"{revalidation_note} "
                    "Revise e valide cada regra antes de ativar o dose_safety."
                ),
                "summary": summary.as_dict(),
            },
            status=status.HTTP_201_CREATED,
        )
