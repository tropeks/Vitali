"""
Terminology search service (Sprint E1-T4 · generalized in A1-T1)
================================================================
Unified, ranked lookup over the governed terminology catalogs — the
"type-and-find-the-code" autocomplete feel. Registers CID-10 plus the SHARED
master-data catalogs CBO / CNES / LOINC / UCUM; adding a future catalog is a
one-line registry entry.

Ranking (best first): exact code > code prefix > display prefix > display
substring, then by code. Matching is accent- AND case-insensitive via the
precomputed normalized column (folded in Python at write time), so it needs NO
Postgres ``unaccent`` extension and degrades gracefully where the extension is
absent. Only ``active`` rows are returned.

Two catalog shapes coexist. ``CID10Code`` carries a ``description`` /
``normalized_description`` vocabulary plus a self-referential ``parent`` and a
chapter/group/category hierarchy. The governed :class:`TerminologyCatalog`
subclasses (CBO/CNES/LOINC/UCUM) carry ``display`` / ``normalized_display`` and
their own flat per-system context columns. ``_serialize`` normalizes both into a
single ``{system, code, display, active, context}`` result shape.
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, Value, When

from apps.core.cbo_cnes_models import CBOCode, CNESEstablishment
from apps.core.loinc_models import LoincCode, UcumUnit
from apps.core.models import CID10Code
from apps.core.terminology_base import normalize_text

# Registry: terminology system id → catalog model.
_SYSTEMS: dict[str, type] = {
    "cid10": CID10Code,
    "cbo": CBOCode,
    "cnes": CNESEstablishment,
    "loinc": LoincCode,
    "ucum": UcumUnit,
}

# CID-10 keeps the legacy ``description`` vocabulary + a ``parent`` hierarchy; the
# governed TerminologyCatalog subclasses use ``display`` / ``normalized_display``.
_LEGACY_DESCRIPTION_SYSTEMS = frozenset({"cid10"})

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


class UnknownTerminologySystem(KeyError):
    """Raised when a caller asks for a terminology system that is not registered."""


def get_model(system: str):
    try:
        return _SYSTEMS[system]
    except KeyError as exc:
        raise UnknownTerminologySystem(system) from exc


def _normalized_field(system: str) -> str:
    """Name of the accent/case-folded search column for ``system``."""
    return (
        "normalized_description" if system in _LEGACY_DESCRIPTION_SYSTEMS else "normalized_display"
    )


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
    norm_field = _normalized_field(system)

    match = Q(code__iexact=q) | Q(code__istartswith=q)
    if norm_q:
        match |= Q(**{f"{norm_field}__contains": norm_q})

    qs = model.objects.filter(active=True)
    # Only CID-10 has a self-referential parent to prefetch for its context.
    if system in _LEGACY_DESCRIPTION_SYSTEMS:
        qs = qs.select_related("parent")

    qs = (
        qs.filter(match)
        .annotate(
            _rank=Case(
                When(code__iexact=q, then=Value(0)),
                When(code__istartswith=q, then=Value(1)),
                When(**{f"{norm_field}__startswith": norm_q}, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by("_rank", "code")[:limit]
    )
    return [_serialize(system, row) for row in qs]


def _context(system: str, row) -> dict:
    """Per-system context payload (the columns the UI shows alongside the code)."""
    if system == "cid10":
        parent = row.parent
        return {
            "chapter": row.chapter,
            "group": row.group,
            "category": row.category,
            "parent": ({"code": parent.code, "display": parent.description} if parent else None),
        }
    if system == "cbo":
        return {"family": row.family}
    if system == "cnes":
        return {
            "establishment_type": row.establishment_type,
            "municipality_ibge": row.municipality_ibge,
        }
    if system == "loinc":
        return {
            "component": row.component,
            "property": row.property,
            "loinc_system": row.loinc_system,
        }
    # ucum (and any future flat catalog) carries no extra context columns.
    return {}


def _serialize(system: str, row) -> dict:
    display = row.description if system in _LEGACY_DESCRIPTION_SYSTEMS else row.display
    return {
        "system": system,
        "code": row.code,
        "display": display,
        "active": row.active,
        "context": _context(system, row),
    }
