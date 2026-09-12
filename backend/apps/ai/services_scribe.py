"""
S-069: AI Clinical Scribe service.

Converts a clinical transcription into a structured SOAP note using Claude.

Key design decisions:
- Uses claude-haiku-4-5-20251001 (cost-efficient, P50 ~400ms).
- SOAP fields are returned as JSON; markdown fences are stripped before parsing.
- Fail-open on LLM/parse errors: returns a degraded result (empty fields).
- Onda 3 / 3.2: AIDPAStatus (+ global flag + monthly ceiling) is now ALSO
  enforced here via requires_ai_consent("scribe", ...), not just in the view
  (ScribeStartView). The view's own DPA check stays as a fast UX-facing 403;
  this is the authoritative gate for every caller, including the async
  Celery task, which had NO consent check of its own before this change.
- Onda 3 / 3.1: the transcription is scrubbed (apps.ai.phi_scrubber) against
  the encounter's Patient before it is ever sent to Claude. See
  phi_scrubber's module docstring for exactly what that does and does not
  catch — it is not a guarantee the transcription is PHI-free.
"""

import json
import logging
import re

from apps.ai.consent import requires_ai_consent
from apps.ai.gateway import ClaudeGateway, LLMGatewayError
from apps.ai.models import AIUsageLog
from apps.ai.phi_scrubber import scrub_for_llm

logger = logging.getLogger(__name__)

_EMPTY_SOAP = {"subjective": "", "objective": "", "assessment": "", "plan": ""}

SCRIBE_SYSTEM_PROMPT = """You are a clinical documentation assistant for Brazilian healthcare.
Convert the provided clinical transcription into a structured SOAP note.
Respond ONLY with a valid JSON object (no markdown, no prose) with these keys:
{
  "subjective": "patient complaints and history in the patient's own words",
  "objective": "examination findings, vitals, and observable data",
  "assessment": "diagnosis or differential diagnoses with CID-10 codes when identifiable",
  "plan": "treatment plan, prescriptions, follow-up instructions"
}
Write in Portuguese (Brazil). Be concise and clinically accurate.
If a section has no content in the transcription, use an empty string."""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that Claude sometimes wraps JSON in."""
    return _FENCE_RE.sub("", raw.strip()).strip()


def _parse_soap_json(raw: str) -> dict:
    """
    Parse SOAP JSON from Claude response.
    Strips markdown fences, validates expected keys.
    Returns empty-field dict on any parse error.
    """
    EMPTY = _EMPTY_SOAP
    try:
        cleaned = _strip_fences(raw)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            logger.warning("services_scribe: expected dict, got %s", type(data))
            return EMPTY
        return {
            "subjective": str(data.get("subjective", "")),
            "objective": str(data.get("objective", "")),
            "assessment": str(data.get("assessment", "")),
            "plan": str(data.get("plan", "")),
        }
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("services_scribe: JSON parse failed — %s | raw=%r", exc, raw[:200])
        return EMPTY


def _log_scribe_usage(event_type: str, input_text: str = "") -> None:
    try:
        AIUsageLog.objects.create(event_type=event_type, input_text=input_text[:500])
    except Exception as exc:  # pragma: no cover — audit logging must never break the request
        logger.warning("services_scribe: could not write AIUsageLog: %s", exc)


def generate_soap(
    transcription: str,
    timeout: int = 30,
    patient: object | None = None,
    tenant_schema: str | None = None,
) -> dict:
    """
    Generate a SOAP note from a clinical transcription.

    Args:
        transcription: Free-form clinical transcription text.
        timeout: LLM call timeout in seconds.
        patient: the encounter's Patient (duck-typed — see phi_scrubber),
            used for directed de-identification. None disables that step
            (generic regex scrubbing still runs).
        tenant_schema: if provided, gates the call through
            requires_ai_consent("scribe", tenant_schema) — global flag,
            signed DPA, monthly ceiling. If None (legacy/unit-test callers),
            NO consent check runs here; callers that skip this MUST enforce
            consent themselves before calling.

    Returns:
        dict with keys: subjective, objective, assessment, plan.
        On any failure — including consent denial — returns a dict with
        empty strings (fail-open in shape, fail-closed in effect: nothing
        was sent to the LLM).
    """
    if not transcription or not transcription.strip():
        return dict(_EMPTY_SOAP)

    if tenant_schema is not None:
        consent = requires_ai_consent("scribe", tenant_schema)
        if not consent.allowed:
            logger.warning(
                "services_scribe: consent denied (%s) for tenant=%s", consent.reason, tenant_schema
            )
            _log_scribe_usage(event_type="degraded")
            return dict(_EMPTY_SOAP)

    scrubbed_transcription = scrub_for_llm(transcription.strip(), patient=patient)

    gateway = ClaudeGateway(timeout=timeout)
    try:
        raw, tokens_in, tokens_out = gateway.complete(
            system=SCRIBE_SYSTEM_PROMPT,
            user=f"Transcription:\n\n{scrubbed_transcription}",
            max_tokens=1024,
        )
        logger.info(
            "services_scribe: generated SOAP in=%d out=%d",
            tokens_in,
            tokens_out,
        )
        AIUsageLog.objects.create(
            event_type="llm_call",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            input_text=scrubbed_transcription[:500],
        )
        return _parse_soap_json(raw)
    except LLMGatewayError as exc:
        logger.warning("services_scribe: LLM error — %s", exc)
        _log_scribe_usage(event_type="degraded", input_text=scrubbed_transcription)
        return dict(_EMPTY_SOAP)
