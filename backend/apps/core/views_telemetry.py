"""Wedge operational telemetry (S30-04).

A single read-only endpoint that surfaces per-wedge operational metrics for the
three deterministic safety wedges (no-show, stockout, deterioration). It does NOT
re-run any engine — it reads the persisted verdict rows and the AuditLog flywheel
trail that already exist per tenant.

POSTURE — read-only/observability. Wedges are pure deterministic algorithms, so
there is no model/latency/confidence to report: ``engine`` is always
``"deterministic"``. We NEVER fabricate a metric that cannot be computed: a wedge
whose verdict model has no ``outcome`` field reports ``outcome_counts: null``, and
``override_rate`` is ``null`` whenever there are zero alerts in the window
(division by zero).

Tenant isolation: the three verdict models are per-tenant (django-tenants routes
every query through the current schema automatically), and AuditLog is a shared
table read through :meth:`AuditLog.for_current_tenant` so the schema discriminator
is applied.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import GlosaSafetyAlert
from apps.core.models import AuditLog, FeatureFlag
from apps.emr.models import AISafetyAlert, DeteriorationAlert, NoShowRisk
from apps.pharmacy.models import ControlledAlert, StockAlert

DEFAULT_WINDOW_DAYS = 30

# Each wedge is described declaratively so the view body stays a single loop.
#   key            — module_key (also the FeatureFlag key)
#   model          — the persisted verdict model (per-tenant)
#   filters        — extra queryset filters narrowing the model to this wedge
#   audit_prefix   — AuditLog.action prefix for "<prefix>_graded" flywheel rows
#   has_outcome    — whether the model carries an ``outcome`` field (else null)
WEDGES: list[dict] = [
    {
        "key": "no_show_prediction",
        "model": NoShowRisk,
        "filters": {},
        "audit_prefix": "no_show_prediction",
        "has_outcome": True,
    },
    {
        "key": "stockout_safety",
        "model": StockAlert,
        "filters": {"kind": "stockout_risk"},
        "audit_prefix": "stockout_prediction",
        "has_outcome": True,
    },
    {
        "key": "deterioration_safety",
        "model": DeteriorationAlert,
        "filters": {},
        "audit_prefix": "deterioration_alert",
        # DeteriorationAlert has no ``outcome`` field — never invent one.
        "has_outcome": False,
    },
    # ── Wave 2 (data-dependent; inert until feature flag enabled per tenant) ───
    {
        "key": "dose_safety",
        "model": AISafetyAlert,
        # source=engine rows are the deterministic verdict; source=llm rows are
        # LLM-explainer siblings and must not double-count the alert.
        "filters": {"alert_type": "dose", "source": "engine"},
        "audit_prefix": "dose_safety",
        # AISafetyAlert has no ``outcome`` TextChoices field.
        "has_outcome": False,
    },
    {
        "key": "allergy_safety",
        "model": AISafetyAlert,
        "filters": {"alert_type": "allergy", "source": "engine"},
        "audit_prefix": "allergy_safety",
        "has_outcome": False,
    },
    {
        "key": "glosa_safety",
        "model": GlosaSafetyAlert,
        "filters": {"source": "engine"},
        "audit_prefix": "glosa_safety",
        # GlosaSafetyAlert uses ``was_denied`` (BooleanField), not a TextChoices
        # outcome field — never fabricate outcome_counts.
        "has_outcome": False,
    },
    {
        "key": "controlled_safety",
        "model": ControlledAlert,
        "filters": {},
        "audit_prefix": "controlled_safety",
        # ControlledAlert.outcome has TextChoices (pending/true_positive/false_positive).
        "has_outcome": True,
    },
]


class WedgeTelemetryView(APIView):
    """GET /api/v1/wedge-telemetry/?days=30 — per-wedge operational metrics.

    Read-only. Returns one entry per wedge with alert/ack counts, override rate,
    and the flywheel (outcome distribution + graded-event count). Authentication
    is required; no per-wedge permission floor since this is aggregate
    observability, not patient/inventory data.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = self._parse_days(request.query_params.get("days"))
        since = timezone.now() - timedelta(days=days)
        flags = self._enabled_flags()

        wedges = [self._build_wedge(spec, since, flags) for spec in WEDGES]
        return Response({"days": days, "wedges": wedges})

    @staticmethod
    def _parse_days(raw) -> int:
        """Coerce ?days= to a positive int, falling back to the default."""
        if raw is None:
            return DEFAULT_WINDOW_DAYS
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_WINDOW_DAYS
        return value if value > 0 else DEFAULT_WINDOW_DAYS

    def _enabled_flags(self) -> dict[str, bool]:
        """module_key -> is_enabled for the current tenant (missing = False)."""
        return dict(
            FeatureFlag.objects.filter(
                module_key__in=[w["key"] for w in WEDGES]
            ).values_list("module_key", "is_enabled")
        )

    def _build_wedge(self, spec: dict, since, flags: dict[str, bool]) -> dict:
        model = spec["model"]
        qs = model.objects.filter(created_at__gte=since, **spec["filters"])

        alert_count = qs.count()
        acknowledged_count = qs.filter(status="acknowledged").count()
        override_rate = (
            acknowledged_count / alert_count if alert_count else None
        )

        return {
            "key": spec["key"],
            "enabled": bool(flags.get(spec["key"], False)),
            "alert_count": alert_count,
            "acknowledged_count": acknowledged_count,
            "override_rate": override_rate,
            "flywheel": {
                "outcome_counts": (
                    self._outcome_counts(qs) if spec["has_outcome"] else None
                ),
                "graded_count": self._graded_count(spec["audit_prefix"], since),
            },
            # Wedges are pure deterministic algorithms — no model, no latency.
            "engine": "deterministic",
        }

    @staticmethod
    def _outcome_counts(qs) -> dict[str, int]:
        """outcome -> count for the rows already in the window."""
        rows = qs.values("outcome").annotate(n=Count("id"))
        return {row["outcome"]: row["n"] for row in rows}

    @staticmethod
    def _graded_count(audit_prefix: str, since) -> int:
        """Count tenant-scoped AuditLog rows action="<prefix>_graded" in window."""
        return (
            AuditLog.for_current_tenant()
            .filter(action=f"{audit_prefix}_graded", created_at__gte=since)
            .count()
        )
