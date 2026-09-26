"""
Dose explanation — the LLM only explains, never decides (ordem 028 passo 3).

INTENT v6 §Resultado: "motor determinístico autoritativo (o LLM só explica)".
Before this module, ``PrescriptionSafetyChecker`` asked the LLM to independently
judge "dose" as one more ``VALID_ALERT_TYPES`` — a second, unaccountable opinion
on the SAME question the deterministic engine (``apps.pharmacy.services.
dose_checker``) already answers. ``dose`` is gone from ``VALID_ALERT_TYPES`` and
the prompt (see ``prescription_safety.py``); this module is what replaces it.

Called ONLY from ``apps.emr.services.dose_safety`` (via
``apps.emr.tasks.explain_dose_verdict``), post-commit, whenever the engine
writes or updates a verdict that is neither SAFE nor NOT_APPLICABLE. It:

  1. Re-runs the SAME consent gate as ordem 025 (``requires_ai_consent``,
     re-using the ``prescription_safety`` feature key — same global switch,
     signed DPA, tenant FeatureFlag and monthly ceiling; no new consent surface).
  2. Re-runs the same rate-limit / circuit-breaker fail-open checks.
  3. Sends the LLM the ENGINE'S verdict (band, ceiling, rule, status_validacao,
     deterministic reason) and asks for prose ONLY — never a new judgement.
  4. Writes the explanation on its OWN row: ``AISafetyAlert(source="llm",
     alert_type="dose_explicacao", explica=<engine alert>, severity="caution")``.
     It NEVER writes/updates the engine's row (``alert_type="dose"``), never
     changes severity/status, and never exists without the engine alert it
     points at (``update_or_create`` keyed on prescription_item + alert_type +
     source, exactly like every other AISafetyAlert upsert).

Fail-open throughout, like ``PrescriptionSafetyChecker``: any gate closed, any
LLM/network error, any malformed response → no explanation row is written, and
the engine's verdict is completely unaffected either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.db import connection

from apps.ai.circuit_breaker import is_open, record_failure, record_success
from apps.ai.consent import requires_ai_consent
from apps.ai.gateway import ClaudeGateway, LLMGatewayError
from apps.ai.phi_scrubber import scrub_generic
from apps.ai.rate_limiter import is_rate_limited
from apps.ai.services import _log_usage, get_tenant_ai_config, increment_monthly_tokens

logger = logging.getLogger(__name__)

# Reuse the ordem 025 gate wholesale (same provider, same DPA, same tenant
# FeatureFlag, same monthly ceiling) — this is an explanation OF a
# prescription-safety verdict, not a new AI surface that would need its own
# consent row and its own line in the DPA text.
_CONSENT_FEATURE_KEY = "prescription_safety"
_CIRCUIT_FEATURE_KEY = "prescription_safety"

_MAX_TOKENS = 300


@dataclass(frozen=True)
class VerdictContext:
    """The engine's verdict, exactly as ``dose_safety`` wrote it — no new
    numbers are computed or guessed here."""

    verdict: str
    reason: str
    status_validacao: str
    expected_low: str | None = None
    expected_high: str | None = None
    max_per_dose: str | None = None
    rule_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerdictContext:
        return cls(
            verdict=str(data.get("verdict", "")),
            reason=str(data.get("reason", "")),
            status_validacao=str(data.get("status_validacao", "nao_validado")),
            expected_low=data.get("expected_low"),
            expected_high=data.get("expected_high"),
            max_per_dose=data.get("max_per_dose"),
            rule_id=data.get("rule_id"),
        )


def _build_prompt(drug_name: str, context: VerdictContext) -> tuple[str, str]:
    system_prompt = (
        "Você é um farmacêutico clínico explicando, em português, o veredito de um "
        "motor determinístico de checagem de dose a um prescritor. O motor já "
        "decidiu — você SÓ explica a decisão dele, em até 3 frases curtas. Nunca "
        "sugira uma dose diferente, nunca contradiga o veredito, nunca invente um "
        "número que não esteja no veredito informado. Se a regra ainda não foi "
        "validada por um farmacêutico, diga isso ao prescritor. Responda APENAS "
        'com um JSON no formato {"explanation": "..."}. Não inclua nenhum outro '
        "texto."
    )
    band = (
        f"{context.expected_low}–{context.expected_high}"
        if context.expected_low and context.expected_high
        else "não calculada"
    )
    user_prompt = (
        f"Medicamento: {drug_name}\n"
        f"Veredito do motor: {context.verdict}\n"
        f"Faixa esperada: {band}\n"
        f"Teto por administração: {context.max_per_dose or 'não aplicável'}\n"
        f"Situação da regra: {context.status_validacao}\n"
        f"Motivo determinístico (do motor): {context.reason}\n\n"
        "Explique este veredito ao prescritor, em até 3 frases, sem sugerir dose."
    )
    return system_prompt, user_prompt


def _call_llm_and_write(schema_name: str, engine_alert, context: VerdictContext) -> None:
    """The part that actually talks to Anthropic and persists the explanation.

    Split out of ``explain_dose_verdict`` purely for readability — every gate
    (consent, rate limit, circuit breaker) has already passed by the time this
    runs. Fail-open: any LLM/parse error returns without writing anything.
    """
    from apps.emr.models import AISafetyAlert

    item = engine_alert.prescription_item
    drug_name = item.generic_name or (
        item.drug.name if item.drug_id else "Medicamento desconhecido"
    )
    system_prompt, user_prompt = _build_prompt(drug_name, context)

    try:
        gateway = ClaudeGateway()
        text, tokens_in, tokens_out = gateway.complete(
            system=system_prompt, user=user_prompt, max_tokens=_MAX_TOKENS
        )
        record_success(schema_name, _CIRCUIT_FEATURE_KEY)
        increment_monthly_tokens(schema_name, tokens_in + tokens_out)
        _log_usage(
            event_type="llm_call",
            input_text=scrub_generic(user_prompt),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    except LLMGatewayError:
        record_failure(schema_name, _CIRCUIT_FEATURE_KEY)
        _log_usage(event_type="degraded", input_text=scrub_generic(user_prompt))
        logger.warning("LLM error during dose explanation", exc_info=True)
        return
    except Exception:
        logger.warning("Unexpected error during dose explanation", exc_info=True)
        return

    explanation = _parse_explanation(text)
    if not explanation:
        return

    AISafetyAlert.objects.update_or_create(
        prescription_item=item,
        alert_type="dose_explicacao",
        source=AISafetyAlert.Source.LLM,
        defaults={
            "severity": "caution",
            "status": "flagged",
            "message": explanation,
            "explica": engine_alert,
        },
    )


def _parse_explanation(text: str) -> str:
    import json

    try:
        data = json.loads(text)
        return str(data.get("explanation", "")).strip()
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.warning("Failed to parse LLM dose-explanation response: %s", text[:200])
        return ""


def _consent_and_breakers_clear(schema_name: str) -> bool:
    """True iff every fail-open gate (consent, rate limit, circuit breaker)
    allows this call to proceed."""
    consent = requires_ai_consent(_CONSENT_FEATURE_KEY, schema_name)
    if not consent.allowed:
        logger.debug("dose explanation consent denied (%s) for %s", consent.reason, schema_name)
        return False

    config = get_tenant_ai_config(schema_name)
    try:
        if is_rate_limited(schema_name, limit=getattr(config, "rate_limit_per_hour", 500)):
            logger.warning("Rate limit exceeded for dose explanation in %s", schema_name)
            return False
    except Exception:
        pass  # fail-open — an unavailable rate limiter must never block the call

    try:
        if is_open(schema_name, _CIRCUIT_FEATURE_KEY):
            logger.warning("Circuit breaker OPEN for dose explanation in %s", schema_name)
            return False
    except Exception:
        pass  # fail-open — an unavailable circuit-breaker store must never block the call

    return True


def explain_dose_verdict(alert_id: str, verdict_context: dict[str, Any]) -> None:
    """Ask the LLM to explain (never decide) one engine dose verdict.

    Fail-open at every step: returns silently (writes nothing) whenever consent
    is denied, the rate limit / circuit breaker trips, or the LLM call/parse
    fails. Never raises to the caller (the Celery task wraps it for retries on
    truly transient errors only).
    """
    from apps.emr.models import AISafetyAlert

    try:
        engine_alert = AISafetyAlert.objects.select_related("prescription_item__drug").get(
            id=alert_id
        )
    except AISafetyAlert.DoesNotExist:
        logger.warning("explain_dose_verdict: alert %s not found — skipping", alert_id)
        return

    # Defensive: this task only ever explains an ENGINE dose verdict. If it
    # somehow got queued for anything else, do nothing rather than guess.
    if engine_alert.source != AISafetyAlert.Source.ENGINE or engine_alert.alert_type != "dose":
        logger.warning(
            "explain_dose_verdict: alert %s is not an engine dose verdict — skipping", alert_id
        )
        return

    schema_name = connection.schema_name  # type: ignore[attr-defined]
    if not _consent_and_breakers_clear(schema_name):
        return

    context = VerdictContext.from_dict(verdict_context)
    _call_llm_and_write(schema_name, engine_alert, context)
