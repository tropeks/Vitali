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
