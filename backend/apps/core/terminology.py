"""
Terminology search service (Sprint E1-T4)
=========================================
Unified, ranked lookup over the governed terminology catalogs — the
"type-and-find-the-code" autocomplete feel. Currently registers CID-10; adding a
future catalog is a one-line registry entry.

Ranking (best first): exact code > code prefix > display prefix > display
substring, then by code. Matching is accent- AND case-insensitive via the
precomputed ``normalized_description`` column (folded in Python at write time),
so it needs NO Postgres ``unaccent`` extension and degrades gracefully where the
extension is absent. Only ``active`` rows are returned. CID-10 results carry
their hierarchy context (chapter/group/category/parent).
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, Value, When

from apps.core.models import CID10Code
from apps.core.terminology_base import normalize_text

# Registry: terminology system id → catalog model.
_SYSTEMS: dict[str, type] = {
    "cid10": CID10Code,
}

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


class UnknownTerminologySystem(KeyError):
    """Raised when a caller asks for a terminology system that is not registered."""


def get_model(system: str):
    try:
        return _SYSTEMS[system]
    except KeyError as exc:
        raise UnknownTerminologySystem(system) from exc


def search(system: str, q: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Ranked, accent/case-insensitive, active-only search over a catalog.

    Returns a list of result dicts (see ``_serialize``). An empty/whitespace
    query returns ``[]``. Raises :class:`UnknownTerminologySystem` for an
    unregistered ``system``.
    """
    model = get_model(system)
    q = (q or "").strip()
    if not q:
        return []
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    norm_q = normalize_text(q)

    match = Q(code__iexact=q) | Q(code__istartswith=q)
    if norm_q:
        match |= Q(normalized_description__contains=norm_q)

    qs = (
        model.objects.filter(active=True)
        .select_related("parent")
        .filter(match)
        .annotate(
            _rank=Case(
                When(code__iexact=q, then=Value(0)),
                When(code__istartswith=q, then=Value(1)),
                When(normalized_description__startswith=norm_q, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by("_rank", "code")[:limit]
    )
    return [_serialize(system, row) for row in qs]


def _serialize(system: str, row) -> dict:
    data = {
        "system": system,
        "code": row.code,
        "display": row.description,
        "active": row.active,
    }
    if system == "cid10":
        parent = row.parent
        data["context"] = {
            "chapter": row.chapter,
            "group": row.group,
            "category": row.category,
            "parent": ({"code": parent.code, "display": parent.description} if parent else None),
        }
    return data
