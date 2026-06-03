"""Stockout-safety orchestrator — stockout-prediction wedge PR S2.

Bridges the PURE deterministic engine (``apps.pharmacy.services.stockout_checker``)
to the pharmacy side-effects: resolving each product's REAL current balance and
trailing dispense history from ``StockItem`` / ``StockMovement``, running the
stockout + expiry-waste predictors, writing each finding to a
``StockAlert(source="engine")``, and recording the flywheel ``AuditLog``. The
engine DECIDES; this service persists.

Mirrors ``apps.billing.services.glosa_safety.GlosaSafetyService``:
  * service-layer orchestrator, NOT signals;
  * atomic DB block; one AuditLog per side-effect with the labeled-example
    fields (drug/material, kind, predicted_date, balance, velocity) for the S4
    flywheel;
  * idempotent update_or_create keyed on the UniqueConstraint — never clobbers an
    acknowledged override unless the message genuinely changed;
  * ONE query per product for the dispense history (no per-item N+1), and a
    single batched query for evaluate_all (mirrors the glosa auth single-query);
  * feature flag ``stockout_safety`` (default OFF). When off, evaluate_item /
    evaluate_all are no-ops — no StockAlert is ever written.

POSTURE — ADVISE, NEVER BLOCK. There is no DispenseView gate (rejected in the
locked design). The wedge is proactive only: the engine forecasts, this service
persists advise-only StockAlerts for the supply manager's dashboard (S3).
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import Q, Sum

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.pharmacy.models import Drug, Material, StockAlert, StockItem, StockMovement
from apps.pharmacy.services.stockout_checker import (
    DEFAULT_WINDOW_DAYS,
    KIND_STOCKOUT_RISK,
    StockoutChecker,
    compute_daily_velocity,
    predict_expiry_waste,
)

logger = logging.getLogger(__name__)

STOCKOUT_SAFETY_FEATURE_KEY = "stockout_safety"
ENGINE_VERSION = "s2"

# Only consumption events drive the velocity (LOCKED: movement_type="dispense").
DISPENSE_MOVEMENT_TYPE = "dispense"

# A replenishment landing in the prediction window = the warning was acted on
# (LOCKED: movement_type="purchase_order_receiving"). Used by the S4 flywheel to
# distinguish an INTERCEPTED prediction (system worked) from a FALSE_POSITIVE.
PURCHASE_RECEIPT_MOVEMENT_TYPE = "purchase_order_receiving"

# Days of stock to TARGET on top of the replenishment lead time when sizing a
# reorder suggestion (wedge S3). Matches the 30-day velocity window so the
# suggestion is "lead time + one month of cover". A constant, NOT invented
# supplier data — the suggestion uses only the derived velocity, the configured
# lead time, and the real balance. Establishments tune the realized qty downstream.
DEFAULT_COVERAGE_DAYS = 30

CatalogItem = Drug | Material


def compute_suggested_reorder_qty(
    *,
    current_balance: Decimal,
    daily_velocity: Decimal | None,
    lead_time_days: int | None,
    coverage_days: int = DEFAULT_COVERAGE_DAYS,
) -> Decimal | None:
    """Pure reorder-quantity suggestion for a stockout_risk alert (wedge S3).

    ``ceil(velocity * (lead_time_days + coverage_days) - current_balance)``,
    clamped to ``>= 0``. Returns ``None`` when the inputs are insufficient
    (no velocity history, or no lead time configured) — same inert posture as
    the engine, so we never invent a number. Uses ONLY the derived velocity, the
    configured lead time, and the real on-hand balance — no supplier/contract data.
    Decimal-only; the ceiling rounds up to a whole orderable unit.
    """
    if daily_velocity is None or lead_time_days is None:
        return None
    horizon = Decimal(lead_time_days + coverage_days)
    target = Decimal(daily_velocity) * horizon
    needed = target - Decimal(current_balance)
    if needed <= 0:
        return Decimal("0")
    return needed.quantize(Decimal("1"), rounding=ROUND_CEILING)


class StockoutService:
    """Service-layer orchestrator for the deterministic stockout/expiry engine."""

    def __init__(self, *, requesting_user=None) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    # ── public API ──────────────────────────────────────────────────────────────

    @classmethod
    def is_enabled(cls) -> bool:
        """True if the current tenant has the stockout_safety feature flag on."""
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, STOCKOUT_SAFETY_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve stockout_safety feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    def evaluate_item(self, item: CatalogItem, *, now: datetime.datetime) -> None:
        """Evaluate ONE catalog product (Drug or Material) and persist findings.

        No-op when the flag is off. Resolves the product's real current balance +
        trailing dispense history (ONE StockMovement query), runs the stockout +
        expiry-waste predictors, then upserts/resolves StockAlerts. ``now`` is
        injected so every evaluation is reproducible.
        """
        if not self.is_enabled():
            return

        with transaction.atomic():
            self._evaluate_one(item, now=now)

    def evaluate_all(self, now: datetime.datetime) -> None:
        """Evaluate every CONFIGURED catalog product (lead_time_days set).

        No-op when the flag is off. A product is "configured" when it has a
        ``lead_time_days`` — without it the stockout engine is inert, so there is
        nothing to persist (we still run expiry-waste for configured products
        only, keeping the candidate set bounded and predictable). Dispense
        history is resolved with ONE batched StockMovement query across all
        candidate products (no per-product N+1).
        """
        if not self.is_enabled():
            return

        drugs = list(Drug.objects.filter(lead_time_days__isnull=False))
        materials = list(Material.objects.filter(lead_time_days__isnull=False))
        with transaction.atomic():
            for drug in drugs:
                self._evaluate_one(drug, now=now)
            for material in materials:
                self._evaluate_one(material, now=now)

    # ── flywheel grading (wedge S4) ───────────────────────────────────────────────

    def grade_predictions(self, *, now: datetime.datetime) -> dict[str, int]:
        """Grade every past-due, still-pending ``stockout_risk`` prediction.

        The nightly FLYWHEEL ground-truth step. For each ``StockAlert`` with
        ``kind=stockout_risk``, ``outcome=pending`` and ``predicted_date <=
        now.date()`` (past due), compares the prediction to what ACTUALLY
        happened and stamps ``outcome`` + ``graded_at``:

          1. **true_positive**  — current on-hand balance ``<= 0``: it really
             stocked out. Checked FIRST (LOCKED): a product that received a PO
             but STILL hit zero is a true stockout (the receipt wasn't enough),
             so zero-stock wins over intercepted.
          2. **intercepted**    — else, IF a ``purchase_order_receiving``
             movement landed for the product in ``(created_at, predicted_date]``:
             a replenishment arrived in time → the system WORKED. Explicitly NOT
             a false positive.
          3. **false_positive** — else (balance > 0, no receipt in window):
             consumption slowed / the prediction over-fired.

        ``now`` is injected so grading is reproducible. IDEMPOTENT: only pending
        past-due alerts are candidates, so a re-run grades nothing already
        graded and never regrades. ``expiry_waste`` alerts are NEVER graded here
        (out of scope for S4 — they stay ``pending``).

        FLAG-INDEPENDENT: this only grades already-created alerts (it never
        creates one). If the ``stockout_safety`` flag is/was off there are simply
        no pending alerts and the method is a no-op — so it is safe to run always.

        NO N+1: the on-hand balance for ALL candidate products is resolved in ONE
        aggregate query per product-kind (grouped by drug/material id), and the
        purchase-order receipts in ONE query per kind. The per-alert loop only
        does in-memory dict lookups + the receipt-window test — no DB round-trip
        per alert. Returns counts per outcome for the accuracy summary.
        """
        today = now.date()

        # Candidate set: only stockout_risk, still pending, past-due. expiry_waste
        # is never graded here. This same filter guarantees idempotency — a re-run
        # finds nothing already graded.
        alerts = list(
            StockAlert.objects.filter(
                kind=StockAlert.Kind.STOCKOUT_RISK,
                outcome=StockAlert.Outcome.PENDING,
                predicted_date__isnull=False,
                predicted_date__lte=today,
            )
        )

        counts: dict[str, int] = {
            StockAlert.Outcome.TRUE_POSITIVE: 0,
            StockAlert.Outcome.INTERCEPTED: 0,
            StockAlert.Outcome.FALSE_POSITIVE: 0,
        }
        if not alerts:
            return counts

        drug_ids = {a.drug_id for a in alerts if a.drug_id is not None}
        material_ids = {a.material_id for a in alerts if a.material_id is not None}

        balances = self._grading_balances(drug_ids, material_ids)
        receipts = self._grading_receipts(drug_ids, material_ids)

        with transaction.atomic():
            for alert in alerts:
                key = ("drug", alert.drug_id) if alert.drug_id else ("material", alert.material_id)
                balance = balances.get(key, Decimal("0"))

                # ORDER LOCKED: zero-stock wins over intercepted.
                if balance <= 0:
                    outcome = StockAlert.Outcome.TRUE_POSITIVE
                elif self._receipt_in_window(alert, receipts.get(key, ())):
                    outcome = StockAlert.Outcome.INTERCEPTED
                else:
                    outcome = StockAlert.Outcome.FALSE_POSITIVE

                alert.outcome = outcome
                alert.graded_at = now
                alert.save(update_fields=["outcome", "graded_at", "updated_at"])
                counts[outcome] += 1
                self._audit_graded(alert, outcome=outcome, balance=balance)

        return counts

    @staticmethod
    def _receipt_in_window(alert: StockAlert, receipt_dates) -> bool:
        """True if a purchase_order_receiving landed in ``(created_at, predicted_date]``.

        A replenishment that arrived AFTER the warning was raised and ON OR
        BEFORE the predicted stockout day means the gestor acted on the alert and
        the stockout was averted. ``predicted_date`` is a date; we include the
        whole day by comparing against its end-of-day datetime. ``receipt_dates``
        is the pre-fetched list of receipt timestamps for this product (no
        per-alert DB hit).
        """
        if alert.predicted_date is None:
            # Candidate set already excludes NULL predicted_date; guard for typing.
            return False
        window_end = _end_of_day(alert.predicted_date)
        for ts in receipt_dates:
            if alert.created_at < ts <= window_end:
                return True
        return False

    @staticmethod
    def _grading_balances(drug_ids: set, material_ids: set) -> dict[tuple, Decimal]:
        """Current on-hand balance per product — ONE query per kind, summed in memory.

        balance = SUM(StockItem.quantity) for the product. ONE ``values_list`` per
        kind pulls (product_id, quantity) for all candidate lots, summed by product
        in Python (lot counts per product are bounded; still no per-alert/per-product
        round-trip). Products with no lots are absent → the caller's ``.get(..., 0)``
        treats them as 0 (stocked out). (``.values().annotate()`` would be one fewer
        query but currently crashes the django-stubs mypy plugin.)
        """
        out: dict[tuple, Decimal] = defaultdict(lambda: Decimal("0"))
        if drug_ids:
            for drug_id, qty in StockItem.objects.filter(drug_id__in=drug_ids).values_list(
                "drug_id", "quantity"
            ):
                out[("drug", drug_id)] += Decimal(qty or 0)
        if material_ids:
            for material_id, qty in StockItem.objects.filter(
                material_id__in=material_ids
            ).values_list("material_id", "quantity"):
                out[("material", material_id)] += Decimal(qty or 0)
        return dict(out)

    @staticmethod
    def _grading_receipts(drug_ids: set, material_ids: set) -> dict[tuple, list]:
        """purchase_order_receiving timestamps per product — ONE query per kind.

        Joined through the lot (``stock_item__drug`` / ``stock_item__material``)
        so a receipt against ANY lot of the product counts. Returned as
        product → list[created_at] for the in-memory window test.
        """
        out: dict[tuple, list] = defaultdict(list)
        if drug_ids:
            rows = StockMovement.objects.filter(
                stock_item__drug_id__in=drug_ids,
                movement_type=PURCHASE_RECEIPT_MOVEMENT_TYPE,
            ).values_list("stock_item__drug_id", "created_at")
            for drug_id, ts in rows:
                out[("drug", drug_id)].append(ts)
        if material_ids:
            rows = StockMovement.objects.filter(
                stock_item__material_id__in=material_ids,
                movement_type=PURCHASE_RECEIPT_MOVEMENT_TYPE,
            ).values_list("stock_item__material_id", "created_at")
            for material_id, ts in rows:
                out[("material", material_id)].append(ts)
        return out

    def _audit_graded(self, alert: StockAlert, *, outcome: str, balance: Decimal) -> None:
        """One AuditLog per grading — the persistent accuracy record the flywheel reads."""
        AuditLog.objects.create(
            user=self.requesting_user,
            action="stockout_prediction_graded",
            resource_type="stock_alert",
            resource_id=str(alert.id),
            new_data={
                "correlation_id": self.correlation_id,
                "alert_id": str(alert.id),
                "drug_id": str(alert.drug_id) if alert.drug_id else None,
                "material_id": str(alert.material_id) if alert.material_id else None,
                "kind": alert.kind,
                "predicted_date": (
                    alert.predicted_date.isoformat() if alert.predicted_date else None
                ),
                "outcome": outcome,
                "balance": str(balance),
            },
        )

    # ── core evaluation (DB-derived inputs → pure engine → persistence) ───────────

    def _evaluate_one(self, item: CatalogItem, *, now: datetime.datetime) -> None:
        is_drug = isinstance(item, Drug)

        current_balance = self._current_balance(item, is_drug=is_drug)
        dispense_events = self._dispense_history(item, is_drug=is_drug, now=now)
        velocity = compute_daily_velocity(dispense_events, now=now)

        # ── stockout risk ─────────────────────────────────────────────────────
        verdict = StockoutChecker.check(
            current_balance=current_balance,
            daily_velocity=velocity,
            lead_time_days=item.lead_time_days,
            safety_stock=item.safety_stock,
            reorder_point=item.reorder_point,
            now=now,
        )
        if verdict.kind == KIND_STOCKOUT_RISK:
            self._upsert_stockout_alert(
                item,
                is_drug=is_drug,
                verdict=verdict,
                current_balance=current_balance,
                velocity=velocity,
            )
        else:
            # sufficient / not_applicable → resolve any stale open stockout alert.
            self._resolve_stockout_alert(item, is_drug=is_drug)

        # ── expiry waste (FEFO) ─────────────────────────────────────────────────
        lots = self._on_hand_lots(item, is_drug=is_drug)
        wastes = predict_expiry_waste(lots, velocity, now)
        fired_stock_item_ids = {w.stock_item_id for w in wastes}
        for waste in wastes:
            self._upsert_expiry_alert(
                item,
                is_drug=is_drug,
                stock_item_id=waste.stock_item_id,
                waste_qty=waste.waste_qty,
                predicted_date=waste.expiry_date,
                message=waste.reason,
                balance=current_balance,
                velocity=velocity,
            )
        self._resolve_stale_expiry_alerts(item, is_drug=is_drug, fired=fired_stock_item_ids)

    # ── DB resolution helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _product_filter(item: CatalogItem, *, is_drug: bool) -> Q:
        """Q matching StockItems for this product on the drug/material FK."""
        return Q(drug=item) if is_drug else Q(material=item)

    def _current_balance(self, item: CatalogItem, *, is_drug: bool) -> Decimal:
        """REAL on-hand balance = SUM of StockItem.quantity for this product.

        ``StockItem.quantity`` is the authoritative per-lot on-hand (maintained
        via F() in StockMovement.save()); the product balance is their sum. ONE
        aggregate query. Empty/no lots → 0.
        """
        total = StockItem.objects.filter(self._product_filter(item, is_drug=is_drug)).aggregate(
            total=Sum("quantity")
        )["total"]
        return Decimal(total) if total is not None else Decimal("0")

    def _dispense_history(
        self, item: CatalogItem, *, is_drug: bool, now: datetime.datetime
    ) -> list[tuple[datetime.datetime, Decimal]]:
        """Trailing dispense events for this product as (timestamp, quantity).

        ONE StockMovement query per product (no per-lot N+1): filter
        movement_type="dispense" joined to the product's StockItems
        (stock_item__drug / stock_item__material) within the trailing velocity
        window, returning only (created_at, quantity). The pure
        compute_daily_velocity takes the magnitudes (dispense quantities are
        stored negative on the ledger; the engine abs()-es them).
        """
        window_start = now - datetime.timedelta(days=DEFAULT_WINDOW_DAYS)
        rel = "stock_item__drug" if is_drug else "stock_item__material"
        rows = StockMovement.objects.filter(
            **{rel: item},
            movement_type=DISPENSE_MOVEMENT_TYPE,
            created_at__gte=window_start,
            created_at__lte=now,
        ).values_list("created_at", "quantity")
        return [(ts, Decimal(qty)) for ts, qty in rows]

    def _on_hand_lots(
        self, item: CatalogItem, *, is_drug: bool
    ) -> list[tuple[object, Decimal, datetime.date | None]]:
        """On-hand lots for this product as (stock_item_id, quantity, expiry_date).

        ONE query: only lots with positive quantity matter for waste. FEFO
        ordering is done inside the pure helper, so we just hand over the raw
        rows.
        """
        rows = (
            StockItem.objects.filter(self._product_filter(item, is_drug=is_drug))
            .filter(quantity__gt=Decimal("0"))
            .values_list("id", "quantity", "expiry_date")
        )
        return [(sid, Decimal(qty), exp) for sid, qty, exp in rows]

    # ── persistence ───────────────────────────────────────────────────────────────

    def _upsert_stockout_alert(
        self,
        item: CatalogItem,
        *,
        is_drug: bool,
        verdict,
        current_balance: Decimal,
        velocity: Decimal | None,
    ) -> None:
        key = self._alert_key(item, is_drug=is_drug, kind=StockAlert.Kind.STOCKOUT_RISK)

        # Reorder suggestion (S3): sized from the derived velocity + configured lead
        # time + real balance — no invented supplier data. None when inert.
        suggested = compute_suggested_reorder_qty(
            current_balance=current_balance,
            daily_velocity=velocity,
            lead_time_days=item.lead_time_days,
        )

        existing = StockAlert.objects.select_for_update().filter(**key).first()

        # Override-preservation (glosa parity): an acknowledged alert for the SAME
        # prediction (unchanged message) must NOT reopen on re-eval — the override
        # stands. A changed prediction (message) reopens it.
        if (
            existing is not None
            and existing.status == StockAlert.Status.ACKNOWLEDGED
            and existing.message == verdict.reason
        ):
            self._audit(
                "stockout_alert_override_kept",
                item,
                is_drug=is_drug,
                kind=StockAlert.Kind.STOCKOUT_RISK,
                predicted_date=verdict.predicted_date,
                balance=current_balance,
                velocity=velocity,
                alert_id=existing.id,
            )
            return

        alert, _created = StockAlert.objects.update_or_create(
            **key,
            defaults={
                "severity": StockAlert.Severity.ADVISE,
                "status": StockAlert.Status.OPEN,
                "predicted_date": verdict.predicted_date,
                "days_to_stockout": verdict.days_to_stockout,
                "predicted_waste_qty": None,
                "suggested_reorder_qty": suggested,
                "engine_version": ENGINE_VERSION,
                "message": verdict.reason,
                # A new/changed prediction reopens, so reset the ack fields.
                "acknowledged_by": None,
                "acknowledged_at": None,
                "note": "",
            },
        )
        self._audit(
            "stockout_alert_raised",
            item,
            is_drug=is_drug,
            kind=StockAlert.Kind.STOCKOUT_RISK,
            predicted_date=verdict.predicted_date,
            balance=current_balance,
            velocity=velocity,
            alert_id=alert.id,
        )

    def _resolve_stockout_alert(self, item: CatalogItem, *, is_drug: bool) -> None:
        """Resolve any stale OPEN/ACKNOWLEDGED stockout_risk alert for the product
        when the engine no longer predicts a risk (sufficient / not_applicable)."""
        key = self._alert_key(item, is_drug=is_drug, kind=StockAlert.Kind.STOCKOUT_RISK)
        stale = (
            StockAlert.objects.select_for_update()
            .filter(**key)
            .exclude(status=StockAlert.Status.RESOLVED)
        )
        for alert in stale:
            alert.status = StockAlert.Status.RESOLVED
            alert.acknowledged_by = None
            alert.acknowledged_at = None
            alert.note = ""
            alert.save(
                update_fields=[
                    "status",
                    "acknowledged_by",
                    "acknowledged_at",
                    "note",
                    "updated_at",
                ]
            )
            self._audit_resolved(item, is_drug=is_drug, alert=alert)

    def _upsert_expiry_alert(
        self,
        item: CatalogItem,
        *,
        is_drug: bool,
        stock_item_id,
        waste_qty: Decimal,
        predicted_date: datetime.date,
        message: str,
        balance: Decimal,
        velocity: Decimal | None,
    ) -> None:
        key = self._alert_key(
            item,
            is_drug=is_drug,
            kind=StockAlert.Kind.EXPIRY_WASTE,
            stock_item_id=stock_item_id,
        )

        existing = StockAlert.objects.select_for_update().filter(**key).first()
        if (
            existing is not None
            and existing.status == StockAlert.Status.ACKNOWLEDGED
            and existing.message == message
        ):
            self._audit(
                "stockout_alert_override_kept",
                item,
                is_drug=is_drug,
                kind=StockAlert.Kind.EXPIRY_WASTE,
                predicted_date=predicted_date,
                balance=balance,
                velocity=velocity,
                alert_id=existing.id,
            )
            return

        alert, _created = StockAlert.objects.update_or_create(
            **key,
            defaults={
                "severity": StockAlert.Severity.ADVISE,
                "status": StockAlert.Status.OPEN,
                "predicted_date": predicted_date,
                "days_to_stockout": None,
                "predicted_waste_qty": waste_qty,
                "engine_version": ENGINE_VERSION,
                "message": message,
                "acknowledged_by": None,
                "acknowledged_at": None,
                "note": "",
            },
        )
        self._audit(
            "stockout_alert_raised",
            item,
            is_drug=is_drug,
            kind=StockAlert.Kind.EXPIRY_WASTE,
            predicted_date=predicted_date,
            balance=balance,
            velocity=velocity,
            alert_id=alert.id,
        )

    def _resolve_stale_expiry_alerts(self, item: CatalogItem, *, is_drug: bool, fired: set) -> None:
        """Resolve open expiry_waste alerts for lots that no longer waste."""
        product_q = Q(drug=item) if is_drug else Q(material=item)
        stale = (
            StockAlert.objects.select_for_update()
            .filter(product_q, kind=StockAlert.Kind.EXPIRY_WASTE, source=StockAlert.Source.ENGINE)
            .exclude(status=StockAlert.Status.RESOLVED)
        )
        for alert in stale:
            if alert.stock_item_id in fired:
                continue
            alert.status = StockAlert.Status.RESOLVED
            alert.acknowledged_by = None
            alert.acknowledged_at = None
            alert.note = ""
            alert.save(
                update_fields=[
                    "status",
                    "acknowledged_by",
                    "acknowledged_at",
                    "note",
                    "updated_at",
                ]
            )
            self._audit_resolved(item, is_drug=is_drug, alert=alert)

    @staticmethod
    def _alert_key(item: CatalogItem, *, is_drug: bool, kind, stock_item_id=None) -> dict:
        """The UniqueConstraint key for update_or_create / lookup."""
        return {
            "drug": item if is_drug else None,
            "material": None if is_drug else item,
            "kind": kind,
            "source": StockAlert.Source.ENGINE,
            "stock_item_id": stock_item_id,
        }

    # ── audit (flywheel) ──────────────────────────────────────────────────────────

    def _audit(
        self,
        action: str,
        item: CatalogItem,
        *,
        is_drug: bool,
        kind: str,
        predicted_date: datetime.date | None,
        balance: Decimal,
        velocity: Decimal | None,
        alert_id,
    ) -> None:
        """One AuditLog per side-effect, carrying the labeled-example flywheel
        fields (drug/material, kind, predicted_date, balance, velocity) for S4."""
        AuditLog.objects.create(
            user=self.requesting_user,
            action=action,
            resource_type="stock_alert",
            resource_id=str(alert_id),
            new_data={
                "correlation_id": self.correlation_id,
                "drug_id": str(item.id) if is_drug else None,
                "material_id": None if is_drug else str(item.id),
                "kind": kind,
                "predicted_date": predicted_date.isoformat() if predicted_date else None,
                "balance": str(balance),
                "velocity": str(velocity) if velocity is not None else None,
                "alert_id": str(alert_id),
            },
        )

    def _audit_resolved(self, item: CatalogItem, *, is_drug: bool, alert: StockAlert) -> None:
        AuditLog.objects.create(
            user=self.requesting_user,
            action="stockout_alert_resolved",
            resource_type="stock_alert",
            resource_id=str(alert.id),
            new_data={
                "correlation_id": self.correlation_id,
                "drug_id": str(item.id) if is_drug else None,
                "material_id": None if is_drug else str(item.id),
                "kind": alert.kind,
                "alert_id": str(alert.id),
            },
        )


def _end_of_day(date_value: datetime.date) -> datetime.datetime:
    """End-of-day datetime for a date, so ``ts <= predicted_date`` includes the
    whole predicted day (a receipt landing ON the predicted date still counts).
    Timezone-aware iff Django is running with USE_TZ (matches StockMovement.created_at).
    """
    from django.utils import timezone as _tz

    naive = datetime.datetime.combine(date_value, datetime.time.max)
    if _tz.is_aware(_tz.now()):
        return _tz.make_aware(naive, _tz.get_current_timezone())
    return naive
