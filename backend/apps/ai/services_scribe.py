"""
S-069: AI Clinical Scribe service.

Converts a clinical transcription into a structured SOAP note using Claude.

Key design decisions:
- Uses claude-haiku-4-5-20251001 (cost-efficient, P50 ~400ms).
- SOAP fields are returned as JSON; markdown fences are stripped before parsing.
- Fail-open: any LLM or parse error returns a degraded result (empty fields).
- AIDPAStatus must be signed before calling (enforced by the view, not here).
"""

import json
import logging
import re

from apps.ai.gateway import ClaudeGateway, LLMGatewayError

logger = logging.getLogger(__name__)

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
    EMPTY = {"subjective": "", "objective": "", "assessment": "", "plan": ""}
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


def generate_soap(transcription: str, timeout: int = 30) -> dict:
    """
    Generate a SOAP note from a clinical transcription.

    Args:
        transcription: Free-form clinical transcription text.
        timeout: LLM call timeout in seconds.

    Returns:
        dict with keys: subjective, objective, assessment, plan.
        On any failure, returns a dict with empty strings (fail-open).
    """
    if not transcription or not transcription.strip():
        return {"subjective": "", "objective": "", "assessment": "", "plan": ""}

    gateway = ClaudeGateway(timeout=timeout)
    try:
        raw, tokens_in, tokens_out = gateway.complete(
            system=SCRIBE_SYSTEM_PROMPT,
            user=f"Transcription:\n\n{transcription.strip()}",
            max_tokens=1024,
        )
        logger.info(
            "services_scribe: generated SOAP in=%d out=%d",
            tokens_in,
            tokens_out,
        )
        return _parse_soap_json(raw)
    except LLMGatewayError as exc:
        logger.warning("services_scribe: LLM error — %s", exc)
        return {"subjective": "", "objective": "", "assessment": "", "plan": ""}
