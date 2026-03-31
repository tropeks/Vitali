"""
TUSSCoder — two-stage retrieval-hybrid TUSS code suggestion.

Stage 1: TUSSCode.search_vector (GIN index, .using('public')) retrieves top 20 candidates.
         Falls back to trigram similarity for Portuguese abbreviations/typos.
Stage 2: Claude re-ranks candidates — can only pick from the provided list (no hallucination).
Stage 3: Validate final selections against TUSSCode DB (anti-hallucination gate).
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from apps.core.models import TUSSCode
from .circuit_breaker import is_open, record_failure, record_success
from .gateway import ClaudeGateway, LLMGatewayError
from .models import AIPromptTemplate, AIUsageLog, TUSSAISuggestion
from .rate_limiter import is_rate_limited

logger = logging.getLogger(__name__)

TUSS_SUGGEST_CACHE_TTL = 86400  # 24 hours


@dataclass
class SuggestionResult:
    tuss_code: str
    description: str
    rank: int
    tuss_code_id: int = 0         # TUSSCode DB PK — needed by frontend for guide item FK
    suggestion_id: str = ''       # TUSSAISuggestion UUID — needed by frontend for feedback


@dataclass
class TUSSCoderResponse:
    suggestions: list[SuggestionResult]
    degraded: bool
    cached: bool


def _cache_key(tenant_schema: str, description: str, guide_type: str, prompt_version: int) -> str:
    """
    Tenant-scoped, context-aware, prompt-versioned cache key.
    Decision A1: guide_type included to avoid wrong-code caching across procedure contexts.
    Decision 18: tenant_schema included to prevent cross-tenant cache leakage.
    """
    normalized = description.strip().lower()
    raw = f"{normalized}|{guide_type}|v{prompt_version}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"ai:tuss:{tenant_schema}:{digest}"


def _get_prompt_template() -> Optional[AIPromptTemplate]:
    try:
        return AIPromptTemplate.objects.filter(name='tuss_suggest', is_active=True).order_by('-version').first()
    except Exception:
        return None


def _retrieve_candidates(description: str) -> list:
    """
    Stage 1: retrieve top 20 TUSSCode candidates.
    Uses .using('public') because TUSSCode lives in the public schema.
    Falls back to trigram similarity if full-text search returns nothing.
    """
    from django.contrib.postgres.search import SearchRank, SearchQuery, TrigramSimilarity

    try:
        # Full-text search (Portuguese config)
        candidates = list(
            TUSSCode.objects.using('public').filter(active=True).annotate(
                rank=SearchRank(F('search_vector'), SearchQuery(description, config='portuguese'))
            ).filter(rank__gt=0).order_by('-rank')[:20]
        )

        if candidates:
            return candidates

        # Trigram fallback for abbreviations, typos, accent variants
        candidates = list(
            TUSSCode.objects.using('public').filter(active=True).annotate(
                rank=TrigramSimilarity('description', description)
            ).filter(rank__gt=0.1).order_by('-rank')[:20]
        )
        return candidates

    except Exception as exc:
        logger.warning("TUSS retrieval error: %s", exc)
        return []


def _call_llm(
    template: AIPromptTemplate,
    description: str,
    guide_type: str,
    candidates: list,
    tenant_schema: str,
) -> tuple[list[SuggestionResult], int, int, int]:
    """
    Stage 2: call Claude to re-rank candidates.
    Returns (suggestions, tokens_in, tokens_out, latency_ms).
    Raises LLMGatewayError on failure.
    """
    candidate_lines = "\n".join(f"{c.code}: {c.description}" for c in candidates)
    # Strip curly braces from user-controlled inputs before .format() to prevent
    # prompt injection via {placeholder} patterns in description or guide_type.
    safe_description = description.replace('{', '').replace('}', '')
    safe_guide_type = (guide_type or "não especificado").replace('{', '').replace('}', '')
    user_prompt = template.user_prompt_template.format(
        guide_type=safe_guide_type,
        description=safe_description,
        candidates=candidate_lines,
    )

    gateway = ClaudeGateway()
    t0 = time.time()
    raw, tokens_in, tokens_out = gateway.complete(
        system=template.system_prompt,
        user=user_prompt,
        max_tokens=256,
    )
    latency_ms = int((time.time() - t0) * 1000)

    # Parse JSON response — strip optional markdown code fence before parsing.
    # Handles: ```json\n{...}\n``` and ```\n{...}\n``` and plain JSON.
    raw = raw.strip()
    if raw.startswith("```"):
        # Drop the opening fence line (e.g. "```json"), take everything after.
        raw = raw[raw.index('\n') + 1:] if '\n' in raw else raw[3:]
        # Drop any trailing closing fence.
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    data = json.loads(raw.strip())
    suggestions_raw = data.get("suggestions", [])

    # Build valid code set from candidates for validation gate
    valid_codes = {c.code: {'description': c.description, 'id': c.id} for c in candidates}

    suggestions = []
    for item in suggestions_raw[:3]:
        code = str(item.get("code", "")).strip()
        if code in valid_codes:
            suggestions.append(SuggestionResult(
                tuss_code=code,
                description=valid_codes[code]['description'],
                rank=len(suggestions) + 1,
                tuss_code_id=valid_codes[code]['id'],
            ))

    return suggestions, tokens_in, tokens_out, latency_ms


def suggest(
    description: str,
    guide_type: str,
    tenant_schema: str,
) -> TUSSCoderResponse:
    """
    Main entry point: returns up to 3 TUSS code suggestions.
    Never raises — always returns TUSSCoderResponse (degraded=True on any failure).
    """
    # Circuit breaker check
    if is_open(tenant_schema):
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Rate limit check
    if is_rate_limited(tenant_schema):
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Get prompt template (needed for cache key version)
    template = _get_prompt_template()
    prompt_version = template.version if template else 0

    # Cache check
    key = _cache_key(tenant_schema, description, guide_type, prompt_version)
    cached_data = cache.get(key)
    if cached_data is not None:
        _log_usage(event_type='cache_hit', input_text=description)
        suggestions = [SuggestionResult(**s) for s in cached_data]
        return TUSSCoderResponse(suggestions=suggestions, degraded=False, cached=True)

    # Stage 1: retrieval
    candidates = _retrieve_candidates(description)
    if not candidates:
        usage_log = _log_usage(event_type='zero_result', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=False, cached=False)

    if not template:
        logger.warning("No active AIPromptTemplate for 'tuss_suggest' — cannot call LLM")
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Stage 2: LLM re-rank
    try:
        suggestions, tokens_in, tokens_out, latency_ms = _call_llm(
            template, description, guide_type, candidates, tenant_schema
        )
        record_success(tenant_schema)
    except LLMGatewayError as exc:
        # API/transport failure — trip the circuit breaker.
        logger.warning("LLM API call failed (tenant=%s): %s", tenant_schema, exc)
        record_failure(tenant_schema)
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)
    except (json.JSONDecodeError, Exception) as exc:
        # Malformed response or unexpected error — do NOT trip the circuit breaker.
        # JSON parse failures are a prompt/model quality issue, not an API outage.
        logger.warning("LLM response parse failed (tenant=%s): %s", tenant_schema, exc)
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Validation dropout check (all suggestions dropped)
    if not suggestions:
        _log_usage(
            event_type='validation_dropout',
            input_text=description,
            template=template,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )
        return TUSSCoderResponse(suggestions=[], degraded=False, cached=False)

    # Log successful call
    usage_log = _log_usage(
        event_type='llm_call',
        input_text=description,
        template=template,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )

    # Create TUSSAISuggestion records for acceptance tracking; attach UUIDs for feedback
    for s in suggestions:
        record = TUSSAISuggestion.objects.create(
            usage_log=usage_log,
            tuss_code=s.tuss_code,
            description=s.description,
            rank=s.rank,
            input_text=description[:500],
            guide_type=guide_type,
        )
        s.suggestion_id = str(record.id)

    # Cache the result
    cache.set(key, [
        {
            'tuss_code': s.tuss_code,
            'description': s.description,
            'rank': s.rank,
            'tuss_code_id': s.tuss_code_id,
            'suggestion_id': s.suggestion_id,
        }
        for s in suggestions
    ], TUSS_SUGGEST_CACHE_TTL)

    return TUSSCoderResponse(suggestions=suggestions, degraded=False, cached=False)


def _log_usage(
    event_type: str,
    input_text: str = '',
    template: Optional[AIPromptTemplate] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
) -> Optional[AIUsageLog]:
    try:
        return AIUsageLog.objects.create(
            prompt_template=template,
            event_type=event_type,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            input_text=input_text[:500],
        )
    except Exception as exc:
        logger.warning("Could not write AIUsageLog: %s", exc)
        return None
