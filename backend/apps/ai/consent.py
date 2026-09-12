"""
apps/ai/consent.py — single consent gate for every outbound call to an AI
provider (Onda 3 / 3.2).

Before this module, each LLM-adjacent feature re-implemented its own subset
of checks: TUSSCoder checked the global flag + tenant flag + ceiling but
never the DPA; GlosaPredictor checked flags/ceiling but never the DPA either;
Scribe left the DPA check to the view (nothing enforced it in the async
Celery task); PrescriptionSafetyChecker (apps/emr/services/prescription_safety.py,
out of this ticket's scope) was the only one that got it right. That drift is
exactly how GlosaPredictor shipped with zero DPA enforcement.

``requires_ai_consent(feature, tenant_schema)`` is now the one place that
checks, in order:
  1. Global kill switch (Django setting, e.g. FEATURE_AI_TUSS).
  2. Signed DPA (LGPD Art. 11 — health data is "dado sensível").
  3. Per-tenant feature toggle (TenantAIConfig), where one is modeled.
  4. Monthly token ceiling.

FAIL-MODE IS DELIBERATELY NOT UNIFORM:

  - DPA signature (step 2) is FAIL-CLOSED, unconditionally. If AIDPAStatus
    cannot be read for any reason (tenant missing, cross-schema query
    erroring, whatever), that is treated as "not signed" and the call is
    blocked. There is no "the DB hiccuped so this consultation's PHI can go
    to Anthropic anyway" exception — LGPD liability does not pause for an
    infra blip. This mirrors what the DPA check already did for
    PrescriptionSafetyChecker/ScribeStart (their docstrings call it
    "fail-open" but the code returns False on error, which IS fail-closed —
    the request is blocked, not allowed).
  - The monthly ceiling (step 4) reuses ``check_monthly_ceiling()``, which
    stays FAIL-OPEN on a Redis outage — same posture as the existing rate
    limiter and circuit breaker (S-030/S-034). That guardrail trio was a
    deliberate availability trade-off made before this ticket and is out of
    scope to flip; only the DPA gate gets the stricter treatment here.
  - Per-tenant toggle (step 3) only applies to features that actually model
    one on ``TenantAIConfig`` (today: tuss, glosa). Scribe and Whisper have
    no per-tenant flag on that model — adding one is an ``apps.core`` change,
    out of scope for this ticket — so that step is skipped for them, which
    matches their pre-existing behavior (global flag + DPA only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

# feature -> (global setting name, TenantAIConfig attribute or None)
_FEATURE_FLAGS: dict[str, tuple[str, str | None]] = {
    "tuss": ("FEATURE_AI_TUSS", "ai_tuss_enabled"),
    "glosa": ("FEATURE_AI_GLOSA", "ai_glosa_prediction_enabled"),
    "scribe": ("FEATURE_AI_SCRIBE", None),
    "whisper": ("FEATURE_WHISPER_FALLBACK", None),
}


@dataclass
class ConsentResult:
    allowed: bool
    reason: str = ""


def _dpa_signed(tenant_schema: str) -> bool:
    """
    Whether the tenant has a signed DPA. FAIL-CLOSED: any lookup failure
    (missing Tenant row, DB error, whatever) returns False = not signed.
    """
    try:
        from apps.core.models import AIDPAStatus, Tenant

        tenant = Tenant.objects.get(schema_name=tenant_schema)
        try:
            return bool(tenant.ai_dpa_status.is_signed)
        except AIDPAStatus.DoesNotExist:
            return False
    except Exception:
        logger.warning(
            "consent: could not resolve DPA status for schema=%s — failing closed", tenant_schema
        )
        return False


def requires_ai_consent(feature: str, tenant_schema: str) -> ConsentResult:
    """
    Returns ConsentResult(allowed=True) only if every gate passes.
    Never raises for a known `feature`; raises ValueError for a typo'd one
    (a programmer error, not a runtime condition to degrade gracefully on).
    """
    if feature not in _FEATURE_FLAGS:
        raise ValueError(f"requires_ai_consent: unknown AI feature {feature!r}")

    global_setting, tenant_attr = _FEATURE_FLAGS[feature]

    if not getattr(settings, global_setting, False):
        return ConsentResult(False, "feature_disabled_global")

    if not _dpa_signed(tenant_schema):
        return ConsentResult(False, "dpa_not_signed")

    if tenant_attr is not None:
        # Local import: apps.ai.services imports this module too (opposite
        # direction), so importing at module load time would be circular.
        from .services import get_tenant_ai_config

        config = get_tenant_ai_config(tenant_schema)
        if not getattr(config, tenant_attr, False):
            return ConsentResult(False, "feature_disabled_tenant")

    from .services import check_monthly_ceiling

    if check_monthly_ceiling(tenant_schema):
        return ConsentResult(False, "monthly_ceiling_exceeded")

    return ConsentResult(True)
