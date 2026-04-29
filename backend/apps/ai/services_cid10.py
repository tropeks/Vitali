"""
S-064: CID-10 AI Suggester.

Two-stage retrieval-hybrid CID-10 code suggestion for diagnosis text.
Clones the TUSSCoder pattern from apps/ai/services.py.

Key design decisions:
- CID10Code lives in PUBLIC schema — always query with .using('public').
- Cache key includes schema_name for LGPD tenant isolation.
- Anti-hallucination gate: validate all LLM suggestions against CID10Code DB.
- Fail-open: any error → CID10SuggesterResponse(suggestions=[], degraded=True).
- Feature flag ai_cid10_suggest (defaults False).
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.cache import cache
from django.db import connections

from apps.ai.circuit_breaker import is_open, record_failure, record_success
from apps.ai.gateway import ClaudeGateway, LLMGatewayError
from apps.ai.rate_limiter import is_rate_limited
from apps.ai.services import get_tenant_ai_config

logger = logging.getLogger(__name__)

# CID10Code lives in the public (shared) schema.
# In production/staging the DB alias is "public"; in the test environment it is "default".
_CID10_DB_ALIAS = "public" if "public" in connections else "default"

CID10_CACHE_TTL = 86400  # 24 hours
MAX_CANDIDATES = 10
MAX_RESULTS = 3


@dataclass
class CID10Suggestion:
    code: str
    description: str
    confidence: int  # 0–100


@dataclass
class CID10SuggesterResponse:
    suggestions: list[CID10Suggestion] = field(default_factory=list)
    degraded: bool = False
    cached: bool = False


def _cache_key(schema_name: str, text: str) -> str:
    """
    Build a tenant-scoped cache key.
    ai:cid10:{schema_name}:{sha256(normalized_text)[:16]}
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"ai:cid10:{schema_name}:{digest}"


def _retrieve_candidates(text: str) -> list:
    """
    Stage 1: Retrieve top MAX_CANDIDATES CID10Code rows from the public schema.

    Uses PostgreSQL full-text search (search_vector) first;
    falls back to trigram similarity for short/abbreviated queries.
    Returns list of dicts: [{code, description}, ...]
    """
    from apps.core.models import CID10Code

    candidates = []

    # Try full-text search first. mypy 1.15's django-stubs plugin crashes on the
    # `.using().filter()` chain — route the manager through Any to sidestep.
    try:
        query = SearchQuery(text, config="portuguese")
        cid_mgr: Any = CID10Code.objects
        qs = (
            cid_mgr.using(_CID10_DB_ALIAS)
            .filter(active=True, search_vector=query)
            .annotate(rank=SearchRank("search_vector", query))
            .order_by("-rank")[:MAX_CANDIDATES]
        )
        candidates = [{"code": c.code, "description": c.description} for c in qs]
    except Exception:
        logger.debug("Full-text search failed, trying trigram", exc_info=True)

    # Trigram fallback if full-text returned fewer than 3 results
    if len(candidates) < 3:
        try:
            from django.contrib.postgres.search import TrigramSimilarity

            # Same mypy-plugin crash workaround.
            cid_mgr2: Any = CID10Code.objects
            qs_trigram = (
                cid_mgr2.using(_CID10_DB_ALIAS)
                .filter(active=True)
                .annotate(similarity=TrigramSimilarity("description", text))
                .filter(similarity__gt=0.1)
                .order_by("-similarity")[:MAX_CANDIDATES]
            )
            existing_codes = {c["code"] for c in candidates}
            for c in qs_trigram:
                if c.code not in existing_codes:
                    candidates.append({"code": c.code, "description": c.description})
                    existing_codes.add(c.code)
        except Exception:
            logger.debug("Trigram fallback also failed", exc_info=True)

    return candidates[:MAX_CANDIDATES]


def _validate_codes(raw_suggestions: list) -> list:
    """
    Stage 3: Anti-hallucination gate.
    Reject any code not found in CID10Code.objects.using('public').
    Returns validated list of CID10Suggestion.
    """
    from apps.core.models import CID10Code

    if not raw_suggestions:
        return []

    codes = [s.get("code", "") for s in raw_suggestions]
    valid_codes = set(
        CID10Code.objects.using(_CID10_DB_ALIAS)
        .filter(code__in=codes, active=True)
        .values_list("code", flat=True)
    )

    validated = []
    for s in raw_suggestions:
        code = s.get("code", "")
        if code in valid_codes:
            try:
                confidence = int(s.get("confidence", 0))
                confidence = max(0, min(100, confidence))
            except (ValueError, TypeError):
                confidence = 0
            validated.append(
                CID10Suggestion(
                    code=code,
                    description=s.get("description", ""),
                    confidence=confidence,
                )
            )
        else:
            logger.debug("Filtered hallucinated CID10 code: %s", code)

    return validated[:MAX_RESULTS]


class CID10Suggester:
    """
    Two-stage retrieval-hybrid CID-10 code suggester.
    Never raises — always returns CID10SuggesterResponse.
    """

    def suggest(self, text: str, schema_name: str) -> CID10SuggesterResponse:
        """
        1. Check feature flag ai_cid10_suggest
        2. Check rate limit / circuit breaker
        3. Normalize text
        4. Cache hit → return cached
        5. Stage 1: DB candidate retrieval (public schema)
        6. Stage 2: LLM re-ranking + confidence assignment
        7. Stage 3: Anti-hallucination validation
        8. Cache result (24h TTL)
        9. Return top 3 suggestions
        """
        # 1. Feature flag
        config = get_tenant_ai_config(schema_name)
        if not getattr(config, "ai_cid10_suggest", False):
            logger.debug("ai_cid10_suggest flag OFF for %s", schema_name)
            return CID10SuggesterResponse(suggestions=[], degraded=False)

        # 2. Rate limit (fail-open)
        try:
            if is_rate_limited(schema_name, limit=getattr(config, "rate_limit_per_hour", 500)):
                logger.warning("Rate limit exceeded for cid10 in %s", schema_name)
                return CID10SuggesterResponse(suggestions=[], degraded=True)
        except Exception:
            pass

        # Circuit breaker (fail-open)
        try:
            if is_open(schema_name, "cid10_suggest"):
                logger.warning("Circuit breaker OPEN for cid10 in %s", schema_name)
                return CID10SuggesterResponse(suggestions=[], degraded=True)
        except Exception:
            pass

        # 3. Normalize
        normalized = text.strip().lower()

        # 4. Cache check
        key = _cache_key(schema_name, normalized)
        cached_data = cache.get(key)
        if cached_data is not None:
            try:
                suggestions = [CID10Suggestion(**s) for s in cached_data]
                return CID10SuggesterResponse(suggestions=suggestions, degraded=False, cached=True)
            except Exception:
                pass  # stale cache — fall through

        # 5. Stage 1: retrieve candidates
        try:
            candidates = _retrieve_candidates(normalized)
        except Exception:
            logger.warning("CID10 candidate retrieval failed", exc_info=True)
            return CID10SuggesterResponse(suggestions=[], degraded=True)

        if not candidates:
            # No candidates in DB — return empty (no LLM call needed)
            return CID10SuggesterResponse(suggestions=[], degraded=False)

        # 6. Stage 2: LLM re-ranking
        try:
            gateway = ClaudeGateway()
            candidates_text = "\n".join(f"{c['code']}: {c['description']}" for c in candidates)
            system_prompt = (
                "Você é um especialista em codificação diagnóstica CID-10 para o Brasil. "
                "Dado um texto de diagnóstico em português, selecione os códigos CID-10 "
                "mais adequados a partir da lista de candidatos fornecida. "
                "Responda APENAS com um array JSON no formato: "
                '[{"code": "X00", "description": "...", "confidence": 85}]. '
                "confidence deve ser um inteiro de 0 a 100. "
                "Retorne no máximo 3 itens, ordenados por relevância decrescente. "
                "Use APENAS códigos da lista de candidatos fornecida."
            )
            user_prompt = (
                f"Texto do diagnóstico: {text}\n\n"
                f"Candidatos disponíveis:\n{candidates_text}\n\n"
                "Retorne um array JSON com os códigos mais adequados."
            )

            response_text, tokens_in, tokens_out = gateway.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=256,
            )
            record_success(schema_name, "cid10_suggest")
        except LLMGatewayError:
            record_failure(schema_name, "cid10_suggest")
            logger.warning("LLM error during CID10 suggestion", exc_info=True)
            return CID10SuggesterResponse(suggestions=[], degraded=True)
        except Exception:
            logger.warning("Unexpected error during CID10 suggestion", exc_info=True)
            return CID10SuggesterResponse(suggestions=[], degraded=True)

        # Parse LLM response
        try:
            raw_suggestions = json.loads(response_text)
            if not isinstance(raw_suggestions, list):
                raise ValueError("Expected JSON array")
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse CID10 LLM response: %s", response_text[:200])
            return CID10SuggesterResponse(suggestions=[], degraded=True)

        # 7. Stage 3: Anti-hallucination validation
        validated = _validate_codes(raw_suggestions)

        # 8. Cache result
        try:
            serializable = [
                {"code": s.code, "description": s.description, "confidence": s.confidence}
                for s in validated
            ]
            cache.set(key, serializable, CID10_CACHE_TTL)
        except Exception:
            pass  # cache failure is non-fatal

        return CID10SuggesterResponse(suggestions=validated, degraded=False, cached=False)
