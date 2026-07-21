"""
Wedge business-value (ROI) computation — issue #123.

`compute_wedge_value_for_tenant` switches into a single tenant schema and derives
business-value metrics for the AI wedges from the deterministic verdict rows the
wedges already write (no new `AIDecisionLog` table — these dedicated alert models
ARE the per-decision logs):

    glosa_safety  → billing.GlosaSafetyAlert  (severity=block/advise, ack = override)
    dose_safety   → emr.AISafetyAlert         (alert_type=dose, source=engine)
    no_show       → emr.NoShowRisk + emr.WaitlistEntry (booked = slot recovered)
    stockout      → pharmacy.StockAlert (kind=stockout_risk) + pharmacy.PurchaseOrder
    deterioration → emr.DeteriorationAlert     (for the override-rate-by-type panel)

Design notes
------------
* Every wedge block is computed under its own ``try/except`` so a missing model,
  an empty tenant, or a half-migrated schema degrades that ONE wedge to a null
  block instead of failing the whole snapshot (the platform dashboard must never
  go blank because one tenant lacks the pharmacy module).
* "Override" everywhere means the operator acknowledged-with-justification the
  wedge's verdict (``acknowledged_at`` set / ``status == acknowledged``). For
  ``dose_safety`` the issue phrases this as alerts "disparados vs ignorados" —
  an ignored/overridden alert is an acknowledged one.
* ROI in R$ is the value the ``glosa_safety`` wedge protected by *blocking* risky
  guide lines: the sum of distinct blocked ``TISSGuideItem.total_value``. Other
  wedges' value is operational (slots recovered, stockouts intercepted) and is
  surfaced as counts rather than reais.
* The metrics dict shape is additive-only — consumers may read any key; never
  remove one. See ``WedgeValueSnapshot``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 30


def _rate(numerator: int, denominator: int) -> float | None:
    """Safe ratio rounded to 3 decimals; None when there is nothing to divide."""
    if not denominator:
        return None
    return round(numerator / denominator, 3)


def _glosa_safety(window_start: Any) -> dict[str, Any]:
    from apps.billing.models import GlosaSafetyAlert

    qs = GlosaSafetyAlert.objects.filter(created_at__gte=window_start)
    fired = qs.count()
    blocked = qs.filter(severity=GlosaSafetyAlert.Severity.BLOCK)
    advise = qs.filter(severity=GlosaSafetyAlert.Severity.ADVISE).count()
    overridden = qs.filter(status=GlosaSafetyAlert.Status.ACKNOWLEDGED).count()

    # R$ protegido: soma do total_value das LINHAS distintas que tiveram um
    # bloqueio item-level. Alertas guide-level (guide_item NULL, ex.: cadastro
    # incompleto) são estruturais, sem valor monetário próprio → não entram.
    blocked_item_ids = (
        blocked.exclude(guide_item__isnull=True).values_list("guide_item_id", flat=True).distinct()
    )
    from apps.billing.models import TISSGuideItem

    blocked_value = TISSGuideItem.objects.filter(id__in=list(blocked_item_ids)).aggregate(
        total=Sum("total_value")
    )["total"] or Decimal("0")

    return {
        "fired": fired,
        "blocked_count": blocked.count(),
        "blocked_value_brl": float(blocked_value),
        "advise_count": advise,
        "overridden": overridden,
        "override_rate": _rate(overridden, fired),
    }


def _dose_safety(window_start: Any) -> dict[str, Any]:
    from apps.emr.models import AISafetyAlert

    # Verdict determinístico do motor de dose (não a explicação LLM).
    qs = AISafetyAlert.objects.filter(
        created_at__gte=window_start,
        alert_type="dose",
        source=AISafetyAlert.Source.ENGINE,
    )
    fired = qs.count()
    overridden = qs.filter(status="acknowledged").count()
    return {
        "fired": fired,
        "overridden": overridden,  # disparados e ignorados (reconhecidos com justificativa)
        "override_rate": _rate(overridden, fired),
    }


def _no_show(window_start: Any) -> dict[str, Any]:
    from apps.emr.models import NoShowRisk, WaitlistEntry

    risk_qs = NoShowRisk.objects.filter(created_at__gte=window_start)
    high_risk = risk_qs.filter(band__in=[NoShowRisk.Band.MEDIUM, NoShowRisk.Band.HIGH]).count()
    true_positives = risk_qs.filter(outcome=NoShowRisk.Outcome.TRUE_POSITIVE).count()

    # Slots recuperados/reagendados: entradas de lista de espera que viraram
    # "booked" (a vaga liberada foi reagendada para outro paciente).
    slots_recovered = WaitlistEntry.objects.filter(
        status="booked", notified_at__gte=window_start
    ).count()

    return {
        "high_risk_flagged": high_risk,
        "true_positives": true_positives,
        "slots_recovered": slots_recovered,
    }


def _stockout(window_start: Any) -> dict[str, Any]:
    from apps.pharmacy.models import PurchaseOrder, StockAlert

    qs = StockAlert.objects.filter(created_at__gte=window_start, kind=StockAlert.Kind.STOCKOUT_RISK)
    alerts = qs.count()
    # outcome=intercepted → "reposição chegou": o alerta levou a uma reposição
    # (criação/recebimento de pedido de compra) que evitou a ruptura.
    intercepted = qs.filter(outcome=StockAlert.Outcome.INTERCEPTED).count()
    pos_created = PurchaseOrder.objects.filter(created_at__gte=window_start).count()
    return {
        "alerts": alerts,
        "intercepted": intercepted,
        "purchase_orders_created": pos_created,
    }


def _deterioration_override(window_start: Any) -> dict[str, int]:
    from apps.emr.models import DeteriorationAlert

    qs = DeteriorationAlert.objects.filter(created_at__gte=window_start)
    fired = qs.count()
    overridden = qs.filter(status=DeteriorationAlert.Status.ACKNOWLEDGED).count()
    return {"fired": fired, "overridden": overridden}


def compute_wedge_value_for_tenant(
    tenant: Any,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: Any = None,
) -> dict[str, Any]:
    """Return the wedge business-value metrics dict for one tenant.

    Runs every query inside ``schema_context(tenant.schema_name)``. Each wedge is
    isolated so one failure (missing module/table) yields ``{"error": ...}`` for
    that wedge only. ``window_days`` is the rolling window the counts cover.
    """
    now = now or timezone.now()
    window_start = now - timedelta(days=window_days)

    metrics: dict[str, Any] = {"window_days": window_days}

    wedges = {
        "glosa_safety": _glosa_safety,
        "dose_safety": _dose_safety,
        "no_show_prediction": _no_show,
        "stockout_safety": _stockout,
    }

    with schema_context(tenant.schema_name):
        for key, fn in wedges.items():
            try:
                metrics[key] = fn(window_start)
            except Exception as exc:  # pragma: no cover - defensive per-wedge guard
                logger.warning(
                    "wedge_value.compute_failed tenant=%s wedge=%s err=%s",
                    tenant.schema_name,
                    key,
                    exc,
                )
                metrics[key] = {"error": str(exc)}

        # Override rate por tipo de wedge (critério de aceitação).
        override_by_wedge: dict[str, Any] = {}
        for key in ("glosa_safety", "dose_safety"):
            block = metrics.get(key) or {}
            if "fired" in block:
                override_by_wedge[key] = {
                    "fired": block["fired"],
                    "overridden": block.get("overridden", 0),
                    "rate": block.get("override_rate"),
                }
        try:
            det = _deterioration_override(window_start)
            override_by_wedge["deterioration"] = {
                "fired": det["fired"],
                "overridden": det["overridden"],
                "rate": _rate(det["overridden"], det["fired"]),
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "wedge_value.deterioration_failed tenant=%s err=%s", tenant.schema_name, exc
            )

        metrics["override_rate_by_wedge"] = override_by_wedge

    # ROI direto em R$ = valor de glosas bloqueadas pelo wedge glosa_safety.
    glosa = metrics.get("glosa_safety") or {}
    metrics["roi_brl"] = float(glosa.get("blocked_value_brl", 0) or 0)

    return metrics
