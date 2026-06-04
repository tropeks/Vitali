"""Allergy-conflict engine (pure, deterministic) — allergy/interaction wedge PR A1.

Given a prescribed drug's identity and the patient's ACTIVE allergies, decides
whether the drug conflicts with a recorded allergy. This is the authoritative
core of the wedge: a positive verdict drives a soft-stop BLOCK at prescription
sign / dispense (the existing LLM checker only *advises*; this *decides the gate*).

Design (mirrors dose_checker / news2):
- **PURE**: no DB, no clock, no LLM, no I/O. Deterministic function of inputs.
- **Matching (LOCKED in eng-review):** normalized **token-subset**. Both the
  allergen and the drug identity are normalised (casefold + strip accents +
  drop punctuation/dose-units/connectors), tokenised on word boundaries, and an
  allergy matches iff its token set is a SUBSET of the drug's token set (union of
  name + generic_name + curated active_ingredients). No raw substring matching —
  that would false-positive ("AAS" inside "AASystem"); token-subset is conservative
  against false positives, and the existing LLM background checker covers the
  fuzzy recall gap as *advise*.
- **Severity-agnostic BLOCK:** ANY direct match of an active allergy is a conflict
  regardless of the recorded severity. Recorded severity is unreliable (a "mild"
  rash years ago can be anaphylaxis today), so the engine never downgrades a match
  to advise on severity grounds — the prescriber must actively override.
- **Never fabricates:** only direct allergen↔drug token matches. Cross-reactivity
  (penicillin→cephalosporin, sulfa) is NOT inferred here — it needs a curated table
  (wedge A2) and is advise, not block.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ENGINE_VERSION = "allergy-a1"

# Verdicts.
VERDICT_SAFE = "safe"
VERDICT_ALLERGY_CONFLICT = "allergy_conflict"
VERDICT_NOT_APPLICABLE = "not_applicable"

# Tokens stripped from BOTH sides before matching: Portuguese connectors and
# dose-form/unit noise that carry no allergen identity. Applied symmetrically so
# the subset test is not skewed.
_NOISE_TOKENS = frozenset(
    {"de", "da", "do", "e", "com", "mg", "ml", "mcg", "g", "ui", "comprimido", "solucao"}
)


def normalize_tokens(text: str | None) -> frozenset[str]:
    """Normalise a drug/allergen string to a set of comparable tokens.

    casefold + strip accents (NFKD, drop combining marks) + split on non-alnum +
    drop pure-digit tokens, single characters, and dose/connector noise.
    """
    if not text:
        return frozenset()
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", no_accents.casefold())
    return frozenset(
        t for t in tokens if len(t) >= 2 and not t.isdigit() and t not in _NOISE_TOKENS
    )


@dataclass(frozen=True)
class AllergyInput:
    """One of the patient's recorded allergies fed to the engine."""

    substance: str
    severity: str = ""  # carried for reporting only — does NOT gate the block


@dataclass(frozen=True)
class AllergyVerdict:
    verdict: str
    # The allergen substances that matched the drug (for the alert message).
    matched_substances: list[str] = field(default_factory=list)
    reason: str = ""
    engine_version: str = ENGINE_VERSION


def _drug_tokens(
    drug_name: str | None,
    drug_generic_name: str | None,
    drug_active_ingredients: list[str] | None,
) -> frozenset[str]:
    tokens: set[str] = set()
    tokens |= normalize_tokens(drug_name)
    tokens |= normalize_tokens(drug_generic_name)
    for ingredient in drug_active_ingredients or []:
        tokens |= normalize_tokens(ingredient)
    return frozenset(tokens)


class AllergyChecker:
    @staticmethod
    def check(
        *,
        drug_name: str | None,
        drug_generic_name: str | None = None,
        drug_active_ingredients: list[str] | None = None,
        allergies: list[AllergyInput],
    ) -> AllergyVerdict:
        """Decide whether the prescribed drug conflicts with an active allergy.

        Returns NOT_APPLICABLE when the drug cannot be identified (no usable
        tokens — we never block on an unidentifiable drug), SAFE when no allergy
        token-set is a subset of the drug's, ALLERGY_CONFLICT otherwise.
        """
        drug_tokens = _drug_tokens(drug_name, drug_generic_name, drug_active_ingredients)
        if not drug_tokens:
            return AllergyVerdict(
                verdict=VERDICT_NOT_APPLICABLE,
                reason="Medicamento sem identificação suficiente para checagem de alergia.",
            )

        matched: list[str] = []
        for allergy in allergies:
            allergy_tokens = normalize_tokens(allergy.substance)
            if allergy_tokens and allergy_tokens.issubset(drug_tokens):
                matched.append(allergy.substance)

        if not matched:
            return AllergyVerdict(verdict=VERDICT_SAFE)

        listed = ", ".join(matched)
        return AllergyVerdict(
            verdict=VERDICT_ALLERGY_CONFLICT,
            matched_substances=matched,
            reason=(
                f"Conflito de alergia: o paciente tem alergia ativa registrada a "
                f"{listed}, presente neste medicamento."
            ),
        )
