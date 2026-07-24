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
VERDICT_ALLERGY_CONFLICT = "allergy_conflict"  # direct match → BLOCK
VERDICT_CROSS_REACTIVITY = "cross_reactivity"  # same curated class → ADVISE
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
    allergen_class: str = ""  # governed AllergenClass name (E2 Allergy FK); "" = legacy text-only


@dataclass(frozen=True)
class CrossReactivityClass:
    """A curated cross-reactivity class fed to the engine (wedge A2).

    ``members`` are ingredient names (INN). The engine matches a member against an
    allergen/drug by the same normalized token-subset rule as the direct match.
    """

    name: str
    members: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AllergyVerdict:
    verdict: str
    # The allergen substances that matched the drug (for the alert message).
    matched_substances: list[str] = field(default_factory=list)
    # For a cross-reactivity verdict, the curated class that links them.
    cross_reactivity_class: str = ""
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


def _member_in(entity_tokens: frozenset[str], members: list[str]) -> bool:
    """True if any curated member ingredient's tokens appear within the entity.

    Same subset rule as the direct match: the member ingredient is "present" iff
    its normalized tokens are a subset of the entity's (drug or allergen) tokens.
    """
    for member in members:
        member_tokens = normalize_tokens(member)
        if member_tokens and member_tokens.issubset(entity_tokens):
            return True
    return False


class AllergyChecker:
    @staticmethod
    def check(
        *,
        drug_name: str | None,
        drug_generic_name: str | None = None,
        drug_active_ingredients: list[str] | None = None,
        allergies: list[AllergyInput],
        cross_reactivity_classes: list[CrossReactivityClass] | None = None,
    ) -> AllergyVerdict:
        """Decide whether the prescribed drug conflicts with an active allergy.

        Priority (highest first): a DIRECT match (allergen token-set ⊆ drug) →
        ALLERGY_CONFLICT (block). Else, if a curated class links an allergen and
        the drug → CROSS_REACTIVITY (advise). Else SAFE. NOT_APPLICABLE when the
        drug cannot be identified (no usable tokens — we never block on that).

        ``cross_reactivity_classes`` is empty by default → no cross-reactivity is
        ever inferred (inert until the establishment curates the classes).
        """
        drug_tokens = _drug_tokens(drug_name, drug_generic_name, drug_active_ingredients)
        if not drug_tokens:
            return AllergyVerdict(
                verdict=VERDICT_NOT_APPLICABLE,
                reason="Medicamento sem identificação suficiente para checagem de alergia.",
            )

        # 1) Direct match (authoritative block).
        matched: list[str] = []
        for allergy in allergies:
            allergy_tokens = normalize_tokens(allergy.substance)
            if allergy_tokens and allergy_tokens.issubset(drug_tokens):
                matched.append(allergy.substance)

        if matched:
            listed = ", ".join(matched)
            return AllergyVerdict(
                verdict=VERDICT_ALLERGY_CONFLICT,
                matched_substances=matched,
                reason=(
                    f"Conflito de alergia: o paciente tem alergia ativa registrada a "
                    f"{listed}, presente neste medicamento."
                ),
            )

        # 2) Cross-reactivity (advise) — only if a curated class links the drug to
        # an allergen that is NOT already a direct match.
        for cls in cross_reactivity_classes or []:
            if not _member_in(drug_tokens, cls.members):
                continue
            for allergy in allergies:
                allergy_tokens = normalize_tokens(allergy.substance)
                # A governed allergen_class is authoritative membership: it triggers
                # cross-reactivity (advise) even when the free-text substance doesn't
                # tokenize to a member. It never upgrades to a direct block (step 1).
                coded_match = bool(allergy.allergen_class) and allergy.allergen_class == cls.name
                if coded_match or (allergy_tokens and _member_in(allergy_tokens, cls.members)):
                    return AllergyVerdict(
                        verdict=VERDICT_CROSS_REACTIVITY,
                        matched_substances=[allergy.substance],
                        cross_reactivity_class=cls.name,
                        reason=(
                            f"Possível reatividade cruzada: alergia a "
                            f"{allergy.substance} e este medicamento pertencem à "
                            f"classe {cls.name}."
                        ),
                    )

        return AllergyVerdict(verdict=VERDICT_SAFE)


# ─── Drug-drug interactions (allergy wedge A3) ────────────────────────────────

# Interaction severities.
INTERACTION_ADVISE = "advise"
INTERACTION_CONTRAINDICATED = "contraindicated"


@dataclass(frozen=True)
class DrugInteractionRule:
    """A curated interaction pair fed to the engine (ingredient names, INN)."""

    ingredient_a: str
    ingredient_b: str
    severity: str = INTERACTION_ADVISE
    description: str = ""


@dataclass(frozen=True)
class DrugInPrescription:
    """A prescription line as seen by the interaction engine."""

    key: str  # stable id (the prescription_item id)
    label: str  # human display (the drug name)
    tokens: frozenset[str]  # normalized identity tokens (name ∪ generic ∪ ingredients)


@dataclass(frozen=True)
class InteractionFinding:
    """One interaction surfaced for a given prescription line."""

    partner_label: str
    severity: str
    description: str = ""


def build_drug_tokens(
    drug_name: str | None,
    drug_generic_name: str | None = None,
    drug_active_ingredients: list[str] | None = None,
) -> frozenset[str]:
    """Public helper: the identity token set used for matching (name ∪ generic ∪ ingr)."""
    return _drug_tokens(drug_name, drug_generic_name, drug_active_ingredients)


def find_interactions(
    drugs: list[DrugInPrescription],
    rules: list[DrugInteractionRule],
) -> dict[str, list[InteractionFinding]]:
    """Pure pairwise interaction scan.

    For each curated rule, find the lines whose tokens contain ingredient A and
    those containing ingredient B; every distinct (A-line, B-line) pair yields a
    symmetric finding on both lines. Returns ``{line.key: [findings]}`` with
    duplicates (same partner+severity) collapsed. A line never interacts with
    itself (a combo drug matching both A and B is not a finding).
    """
    findings: dict[str, list[InteractionFinding]] = {}

    def _add(key: str, finding: InteractionFinding) -> None:
        bucket = findings.setdefault(key, [])
        if not any(
            f.partner_label == finding.partner_label and f.severity == finding.severity
            for f in bucket
        ):
            bucket.append(finding)

    for rule in rules:
        a_tokens = normalize_tokens(rule.ingredient_a)
        b_tokens = normalize_tokens(rule.ingredient_b)
        if not a_tokens or not b_tokens:
            continue
        a_lines = [d for d in drugs if a_tokens.issubset(d.tokens)]
        b_lines = [d for d in drugs if b_tokens.issubset(d.tokens)]
        for da in a_lines:
            for db in b_lines:
                if da.key == db.key:
                    continue
                _add(da.key, InteractionFinding(db.label, rule.severity, rule.description))
                _add(db.key, InteractionFinding(da.label, rule.severity, rule.description))
    return findings
