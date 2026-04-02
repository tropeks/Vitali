"""
AI services — TUSSCoder (S-031) + GlosaPredictor (S-034) + per-tenant config helpers (S-033).

TUSSCoder: two-stage retrieval-hybrid TUSS code suggestion.
  Stage 1: TUSSCode.search_vector (GIN index, .using('public')) retrieves top 20 candidates.
           Falls back to trigram similarity for Portuguese abbreviations/typos.
  Stage 2: Claude re-ranks candidates — can only pick from the provided list (no hallucination).
  Stage 3: Validate final selections against TUSSCode DB (anti-hallucination gate).

GlosaPredictor: zero-shot LLM prediction of denial (glosa) risk per TISS item.
  Input: tuss_code + insurer_ans_code + cid10_codes + guide_type
  Output: risk_level (low/medium/high) + risk_reason + risk_code
  Cache: 24h (insurer rules can change; 7-day TTL would give stale false-negatives)
"""
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Sum
from django.utils import timezone

from apps.core.models import TUSSCode, TenantAIConfig
from .circuit_breaker import is_open, record_failure, record_success
from .gateway import ClaudeGateway, LLMGatewayError
from .models import AIPromptTemplate, AIUsageLog, TUSSAISuggestion
from .rate_limiter import is_rate_limited

logger = logging.getLogger(__name__)

TUSS_SUGGEST_CACHE_TTL = 86400   # 24 hours
GLOSA_PREDICT_CACHE_TTL = 86400  # 24 hours — insurer rules change; longer TTL gives stale negatives
TENANT_AI_CONFIG_CACHE_TTL = 300  # 5 minutes


# ─── Per-Tenant AI Config ─────────────────────────────────────────────────────

def get_tenant_ai_config(schema_name: str):
    """
    Returns the TenantAIConfig for a given schema_name.
    Cached 5 minutes (TENANT_AI_CONFIG_CACHE_TTL). Never raises.
    Falls back to an unsaved TenantAIConfig() with all-disabled defaults if no row exists.
    Note: Django Admin saves do NOT invalidate this cache — ops may see up to 5-minute lag.
    """
    cache_key = f"ai:config:{schema_name}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        config = TenantAIConfig.objects.using("default").get(tenant__schema_name=schema_name)
        cache.set(cache_key, config, TENANT_AI_CONFIG_CACHE_TTL)
        return config
    except Exception:
        # No row exists, or DB error — return safe all-disabled defaults
        default_config = TenantAIConfig()  # unsaved, pk=None, all defaults
        return default_config


def check_monthly_ceiling(schema_name: str) -> bool:
    """
    Returns True if the tenant has exceeded their monthly token ceiling.
    Uses a Redis counter (ai:tokens:{schema}:{YYYY-MM}). On Redis miss, seeds from DB.
    Fail-open: if Redis is unavailable, allows the request.
    """
    config = get_tenant_ai_config(schema_name)
    ceiling = config.monthly_token_ceiling
    month_key = f"ai:tokens:{schema_name}:{date.today().strftime('%Y-%m')}"

    try:
        count = cache.get(month_key)
        if count is None:
            # Redis miss — seed from DB (sargable on created_at index)
            month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            agg = AIUsageLog.objects.filter(
                created_at__range=(month_start, timezone.now())
            ).aggregate(total=Sum(F("tokens_in") + F("tokens_out")))
            count = agg["total"] or 0
            # Compute TTL to end of month
            import calendar
            last_day = calendar.monthrange(month_start.year, month_start.month)[1]
            month_end = month_start.replace(day=last_day, hour=23, minute=59, second=59)
            ttl = max(1, int((month_end - timezone.now()).total_seconds()))
            cache.set(month_key, count, timeout=ttl)

        return int(count) >= ceiling
    except Exception:
        logger.warning("Redis unavailable for monthly ceiling check (tenant=%s) — failing open", schema_name)
        return False


def increment_monthly_tokens(schema_name: str, tokens: int) -> None:
    """Increment the monthly token counter after a successful LLM call. Fail-silently."""
    if tokens <= 0:
        return
    month_key = f"ai:tokens:{schema_name}:{date.today().strftime('%Y-%m')}"
    try:
        try:
            cache.incr(month_key, tokens)
        except ValueError:
            # Key doesn't exist yet — let check_monthly_ceiling seed it on next call
            pass
    except Exception:
        pass


# ─── TUSSCoder ────────────────────────────────────────────────────────────────

@dataclass
class SuggestionResult:
    tuss_code: str
    description: str
    rank: int
    tuss_code_id: int = 0         # TUSSCode DB PK — needed by frontend for guide item FK
    suggestion_id: str = ''       # TUSSAISuggestion UUID — needed by frontend for feedback


@dataclass
class TUSSCoderResponse:
    suggestions: list
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


def _get_prompt_template(name: str = 'tuss_suggest') -> Optional[AIPromptTemplate]:
    try:
        return AIPromptTemplate.objects.filter(name=name, is_active=True).order_by('-version').first()
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
) -> tuple:
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
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw[raw.index('\n') + 1:] if '\n' in raw else raw[3:]
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
    Now uses per-tenant config (TenantAIConfig) for feature toggle, rate limit, and ceiling.
    """
    # Global kill switch first
    if not getattr(settings, 'FEATURE_AI_TUSS', False):
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Per-tenant feature toggle
    config = get_tenant_ai_config(tenant_schema)
    if not config.ai_tuss_enabled:
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Monthly token ceiling
    if check_monthly_ceiling(tenant_schema):
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Circuit breaker check
    if is_open(tenant_schema, feature='tuss'):
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Rate limit check (per-tenant limit)
    if is_rate_limited(tenant_schema, limit=config.rate_limit_per_hour):
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)

    # Get prompt template (needed for cache key version)
    template = _get_prompt_template('tuss_suggest')
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
        _log_usage(event_type='zero_result', input_text=description)
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
        record_success(tenant_schema, feature='tuss')
        increment_monthly_tokens(tenant_schema, tokens_in + tokens_out)
    except LLMGatewayError as exc:
        logger.warning("LLM API call failed (tenant=%s): %s", tenant_schema, exc)
        record_failure(tenant_schema, feature='tuss')
        _log_usage(event_type='degraded', input_text=description)
        return TUSSCoderResponse(suggestions=[], degraded=True, cached=False)
    except (json.JSONDecodeError, Exception) as exc:
        # Malformed response or unexpected error — do NOT trip the circuit breaker.
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


# ─── GlosaPredictor ───────────────────────────────────────────────────────────

@dataclass
class PredictionResult:
    risk_level: str = "low"
    risk_reason: str = ""
    risk_code: str = ""
    degraded: bool = False
    cached: bool = False


def _glosa_cache_key(
    schema_name: str,
    tuss_code: str,
    insurer_ans_code: str,
    cid10_codes: list,
    guide_type: str,
) -> str:
    """Full SHA-256 cache key for glosa predictions. Includes all input dimensions."""
    sorted_cid10 = "|".join(sorted(cid10_codes))
    raw = f"{tuss_code}|{insurer_ans_code}|{sorted_cid10}|{guide_type}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"ai:glosa:{schema_name}:{digest}"


def _sanitize_insurer_name(name: str) -> str:
    """Strip newlines, limit to 100 chars, remove curly braces."""
    name = re.sub(r'[\r\n]', ' ', name)
    name = name.replace('{', '').replace('}', '')
    return name[:100]


def _sanitize_cid10_code(code: str) -> str:
    """Keep only alphanumeric chars from a CID-10 code."""
    return re.sub(r'[^A-Za-z0-9]', '', code)[:10]


def predict_glosa(
    tuss_code: str,
    insurer_ans_code: str,
    insurer_name: str,
    cid10_codes: list,
    guide_type: str,
    schema_name: str,
) -> PredictionResult:
    """
    Predict glosa (denial) risk for a TISS guide item.
    Never raises — returns PredictionResult(degraded=True) on any failure.
    """
    # Global kill switch
    if not getattr(settings, 'FEATURE_AI_GLOSA', True):
        return PredictionResult(risk_level='low', degraded=True)

    # Per-tenant feature toggle
    config = get_tenant_ai_config(schema_name)
    if not config.ai_glosa_prediction_enabled:
        return PredictionResult(risk_level='low', degraded=True)

    # Monthly token ceiling
    if check_monthly_ceiling(schema_name):
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # Circuit breaker (Glosa has its own independent circuit)
    if is_open(schema_name, feature='glosa'):
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # Rate limit (shared per-tenant limit across TUSS + Glosa)
    if is_rate_limited(schema_name, limit=config.rate_limit_per_hour):
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # Prompt injection guard: validate insurer_ans_code format
    if not re.match(r'^[0-9]{1,20}$', insurer_ans_code):
        logger.warning("GlosaPredictor: invalid insurer_ans_code format — fail-open")
        return PredictionResult(risk_level='low', degraded=True)

    # Cache check
    cache_key = _glosa_cache_key(schema_name, tuss_code, insurer_ans_code, cid10_codes, guide_type)
    cached = cache.get(cache_key)
    if cached is not None:
        return PredictionResult(
            risk_level=cached['risk_level'],
            risk_reason=cached['risk_reason'],
            risk_code=cached.get('risk_code', ''),
            degraded=False,
            cached=True,
        )

    # Get prompt template
    template = _get_prompt_template('glosa_predict')
    if not template:
        logger.warning("No active AIPromptTemplate for 'glosa_predict' — fail-open")
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # Build prompt inputs — sanitize all user-controlled fields
    safe_insurer_name = _sanitize_insurer_name(insurer_name)
    safe_guide_type = guide_type.replace('{', '').replace('}', '')[:50]
    safe_cid10 = ", ".join(_sanitize_cid10_code(c) for c in cid10_codes[:20])
    safe_tuss = str(tuss_code).replace('{', '').replace('}', '')[:20]

    try:
        user_prompt = template.user_prompt_template.format(
            tuss_code=safe_tuss,
            insurer_name=safe_insurer_name,
            insurer_ans_code=insurer_ans_code,
            cid10_codes=safe_cid10,
            guide_type=safe_guide_type,
        )
    except (KeyError, ValueError) as exc:
        logger.warning("GlosaPredictor prompt format error: %s", exc)
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # LLM call
    gateway = ClaudeGateway()
    t0 = time.time()
    try:
        raw, tokens_in, tokens_out = gateway.complete(
            system=template.system_prompt,
            user=user_prompt,
            max_tokens=256,
        )
        latency_ms = int((time.time() - t0) * 1000)
        record_success(schema_name, feature='glosa')
        increment_monthly_tokens(schema_name, tokens_in + tokens_out)
    except LLMGatewayError as exc:
        logger.warning("GlosaPredictor LLM API call failed (tenant=%s): %s", schema_name, exc)
        record_failure(schema_name, feature='glosa')
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # Parse response
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw[raw.index('\n') + 1:] if '\n' in raw else raw[3:]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        data = json.loads(raw.strip())
        risk_level = data.get("risk_level", "low").lower()
        if risk_level not in ("low", "medium", "high"):
            risk_level = "low"
        risk_reason = str(data.get("risk_reason", ""))[:500]
        risk_code = str(data.get("risk_code", ""))[:5]
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("GlosaPredictor response parse error (tenant=%s): %s", schema_name, exc)
        _log_usage(event_type='degraded', input_text=tuss_code)
        return PredictionResult(risk_level='low', degraded=True)

    # Log usage
    usage_log = _log_usage(
        event_type='llm_call',
        input_text=f"{tuss_code}|{insurer_ans_code}",
        template=template,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )

    # Persist prediction record
    prediction_id = None
    try:
        from .models import GlosaPrediction
        pred = GlosaPrediction.objects.create(
            tuss_code=tuss_code,
            insurer_ans_code=insurer_ans_code,
            cid10_codes=[_sanitize_cid10_code(c) for c in cid10_codes[:20]],
            guide_type=guide_type,
            risk_level=risk_level,
            risk_reason=risk_reason,
            risk_code=risk_code,
            usage_log=usage_log,
        )
        prediction_id = str(pred.id)
    except Exception as exc:
        logger.warning("Could not create GlosaPrediction record: %s", exc)

    # Cache result
    try:
        cache.set(cache_key, {
            'risk_level': risk_level,
            'risk_reason': risk_reason,
            'risk_code': risk_code,
        }, GLOSA_PREDICT_CACHE_TTL)
    except Exception:
        pass

    result = PredictionResult(
        risk_level=risk_level,
        risk_reason=risk_reason,
        risk_code=risk_code,
        degraded=False,
        cached=False,
    )
    # Attach prediction_id for the view to return (not a formal field — set dynamically)
    result.prediction_id = prediction_id
    return result
