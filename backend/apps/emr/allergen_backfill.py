"""E2-T2 — Allergy substance → AllergenClass reconciliation helper.

Pure function that best-effort maps an ``Allergy``'s free-text ``substance`` onto
a curated ``pharmacy.AllergenClass``: matched → set the FK, unmatched → keep
``substance`` and set ``allergen_unmatched=True`` (NEVER lose data). Takes the
model classes as arguments so the SAME logic runs both from the data migration
(historical models via ``apps.get_model``) and from unit tests (real models).

Matching is deliberately conservative and offline-safe: normalized token match of
the substance against the class ``name`` or any of its ``members`` (the same
normalized-token approach the allergy engine uses). No fuzzy invention.
"""

from __future__ import annotations

import re


def _norm(value: str) -> str:
    """Lowercase, strip accents-insensitively-ish, collapse to word tokens."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _tokens(value: str) -> set[str]:
    return {t for t in _norm(value).split() if t}


def _substance_matches_class(substance: str, allergen_class) -> bool:
    """True when the substance name matches the class name or any member.

    Match = the substance token-set and a candidate (class name or a member)
    share a full token (subset in either direction), e.g. substance
    "penicilina" matches member "penicilina"; substance "amoxicilina 500mg"
    matches member "amoxicilina".
    """
    sub = _tokens(substance)
    if not sub:
        return False
    candidates = [allergen_class.name, *(allergen_class.members or [])]
    for cand in candidates:
        cand_tokens = _tokens(str(cand))
        if not cand_tokens:
            continue
        if cand_tokens & sub:
            return True
    return False


def reconcile_allergies(AllergyModel, AllergenClassModel) -> tuple[int, int]:
    """Link Allergy rows whose ``substance`` matches a curated AllergenClass.

    Only touches rows not already linked. Matched → set ``allergen_class`` and
    clear ``allergen_unmatched``. Unmatched → keep ``substance`` and set
    ``allergen_unmatched=True``. Returns ``(linked, unmatched)``.
    """
    linked = unmatched = 0
    classes = list(AllergenClassModel.objects.all())
    for allergy in AllergyModel.objects.filter(allergen_class__isnull=True).iterator():
        match = next(
            (c for c in classes if _substance_matches_class(allergy.substance, c)),
            None,
        )
        if match is not None:
            allergy.allergen_class_id = match.pk
            allergy.allergen_unmatched = False
            allergy.save(update_fields=["allergen_class", "allergen_unmatched"])
            linked += 1
        else:
            if not allergy.allergen_unmatched:
                allergy.allergen_unmatched = True
                allergy.save(update_fields=["allergen_unmatched"])
            unmatched += 1
    return linked, unmatched
