"""
Pharmacy API views — S-026 Catalog, S-027 Stock, S-028 Dispensation
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import (
    ControlledAlert,
    Dispensation,
    DispensationLot,
    Drug,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    StockAlert,
    StockItem,
    StockMovement,
    Supplier,
)
from .serializers import (
    DispensationSerializer,
    DispenseRequestSerializer,
    DrugSerializer,
    MaterialSerializer,
    POReceiveSerializer,
    PurchaseOrderSerializer,
    StockItemSerializer,
    StockMovementSerializer,
    SupplierSerializer,
)

_PHARMACY_MODULE = ModuleRequiredPermission("pharmacy")


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
        if self.action in ("create", "update", "partial_update", "destroy", "adjust"):
            return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.stock_manage")]
        return [IsAuthenticated(), _PHARMACY_MODULE, HasPermission("pharmacy.read")]

    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        """POST /pharmacy/stock/items/{id}/adjust/ — create an adjustment StockMovement."""
        item = self.get_object()
        quantity = request.data.get("quantity")
        notes = request.data.get("notes", "")
        if quantity is None:
            return Response({"detail": "quantity is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            qty = Decimal(str(quantity))
        except Exception:
            return Response(
                {"detail": "quantity must be a valid number."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            movement = StockMovement.objects.create(
                stock_item=item,
                movement_type="adjustment",
                quantity=qty,
                notes=notes,
                performed_by=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        log_audit(
            request, "adjust", "StockItem", item.id, new_data={"quantity": str(qty), "notes": notes}
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)


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
            role = getattr(request.user, "role", None)
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
