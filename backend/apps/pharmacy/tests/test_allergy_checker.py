"""Pure-engine tests for the allergy-conflict checker (allergy wedge A1).

PURE ENGINE. No DB. Validates the locked normalized token-subset matching:
direct match, accent/case folding, multi-token subset, the active_ingredients
path (brand name + structured ingredient), the substring false-positive guard
("AAS" ∉ "AASystem"), the over-specific-allergy false-negative (documented;
LLM covers recall), severity-agnostic blocking, and the NOT_APPLICABLE /
SAFE inert paths.
"""

from apps.pharmacy.services.allergy_checker import (
    VERDICT_ALLERGY_CONFLICT,
    VERDICT_CROSS_REACTIVITY,
    VERDICT_NOT_APPLICABLE,
    VERDICT_SAFE,
    AllergyChecker,
    AllergyInput,
    CrossReactivityClass,
    normalize_tokens,
)


def _check(drug_name=None, generic=None, ingredients=None, allergies=(), classes=None):
    return AllergyChecker.check(
        drug_name=drug_name,
        drug_generic_name=generic,
        drug_active_ingredients=ingredients,
        allergies=list(allergies),
        cross_reactivity_classes=classes,
    )


_BETA_LACTAMS = CrossReactivityClass(
    name="Beta-lactâmicos",
    members=["penicilina", "amoxicilina", "ampicilina", "cefalexina", "cefalotina"],
)


class TestNormalize:
    def test_casefold_and_accents(self):
        assert normalize_tokens("Ácido Acetilsalicílico") == frozenset(
            {"acido", "acetilsalicilico"}
        )

    def test_drops_digits_units_connectors_and_singletons(self):
        # "500", "mg", "de" and single chars dropped; real tokens kept.
        assert normalize_tokens("Dipirona 500 mg de X") == frozenset({"dipirona"})

    def test_empty(self):
        assert normalize_tokens("") == frozenset()
        assert normalize_tokens(None) == frozenset()


class TestDirectMatch:
    def test_simple_conflict(self):
        v = _check(drug_name="Dipirona 500mg", allergies=[AllergyInput("Dipirona")])
        assert v.verdict == VERDICT_ALLERGY_CONFLICT
        assert v.matched_substances == ["Dipirona"]

    def test_case_and_accent_insensitive(self):
        v = _check(generic="Penicilina G", allergies=[AllergyInput("penicilina")])
        assert v.verdict == VERDICT_ALLERGY_CONFLICT

    def test_matches_via_active_ingredient_when_brand_name_differs(self):
        # Brand name with no generic; the structured ingredient carries the match.
        v = _check(
            drug_name="Novalgina",
            generic="",
            ingredients=["Dipirona"],
            allergies=[AllergyInput("Dipirona")],
        )
        assert v.verdict == VERDICT_ALLERGY_CONFLICT

    def test_multi_token_allergen_subset(self):
        v = _check(
            drug_name="Clavulin",
            ingredients=["Amoxicilina", "Clavulanato"],
            allergies=[AllergyInput("amoxicilina clavulanato")],
        )
        assert v.verdict == VERDICT_ALLERGY_CONFLICT

    def test_severity_is_ignored_mild_still_blocks(self):
        v = _check(drug_name="Dipirona", allergies=[AllergyInput("Dipirona", severity="mild")])
        assert v.verdict == VERDICT_ALLERGY_CONFLICT


class TestNoFalsePositive:
    def test_substring_does_not_match(self):
        # "AAS" must NOT match "AASystem" — token match, not substring.
        v = _check(drug_name="AASystem", allergies=[AllergyInput("AAS")])
        assert v.verdict == VERDICT_SAFE

    def test_unrelated_drug_is_safe(self):
        v = _check(
            drug_name="Paracetamol 750mg",
            ingredients=["Paracetamol"],
            allergies=[AllergyInput("Dipirona")],
        )
        assert v.verdict == VERDICT_SAFE

    def test_over_specific_allergy_is_safe_documented_recall_gap(self):
        # {dipirona, sodica} is NOT a subset of {dipirona} → no block. This is the
        # conservative-against-false-positive trade-off; the LLM advise path covers
        # this recall gap. Documented behaviour, asserted so it stays intentional.
        v = _check(drug_name="Dipirona", allergies=[AllergyInput("Dipirona Sódica")])
        assert v.verdict == VERDICT_SAFE


class TestInert:
    def test_no_allergies_is_safe(self):
        assert _check(drug_name="Dipirona", allergies=[]).verdict == VERDICT_SAFE

    def test_unidentifiable_drug_is_not_applicable(self):
        # No usable tokens anywhere → never block on an unidentifiable drug.
        v = _check(drug_name="", generic="", ingredients=[], allergies=[AllergyInput("Dipirona")])
        assert v.verdict == VERDICT_NOT_APPLICABLE

    def test_blank_allergen_does_not_match(self):
        v = _check(drug_name="Dipirona", allergies=[AllergyInput("   ")])
        assert v.verdict == VERDICT_SAFE


class TestCrossReactivity:
    def test_penicillin_allergy_flags_cephalosporin_as_cross(self):
        # Allergic to penicillin, prescribed cephalexin → same class → advise.
        v = _check(
            drug_name="Cefalexina 500mg",
            ingredients=["Cefalexina"],
            allergies=[AllergyInput("Penicilina")],
            classes=[_BETA_LACTAMS],
        )
        assert v.verdict == VERDICT_CROSS_REACTIVITY
        assert v.cross_reactivity_class == "Beta-lactâmicos"
        assert v.matched_substances == ["Penicilina"]

    def test_no_classes_means_no_cross_reactivity(self):
        # Without curated classes the engine never infers cross-reactivity (inert).
        v = _check(
            drug_name="Cefalexina 500mg",
            ingredients=["Cefalexina"],
            allergies=[AllergyInput("Penicilina")],
            classes=None,
        )
        assert v.verdict == VERDICT_SAFE

    def test_direct_match_wins_over_cross_reactivity(self):
        # Allergic to cephalexin AND prescribed cephalexin → DIRECT conflict (block),
        # not merely cross-reactivity.
        v = _check(
            drug_name="Cefalexina 500mg",
            ingredients=["Cefalexina"],
            allergies=[AllergyInput("Cefalexina")],
            classes=[_BETA_LACTAMS],
        )
        assert v.verdict == VERDICT_ALLERGY_CONFLICT

    def test_unrelated_class_no_cross(self):
        # Drug not in the class → no cross-reactivity.
        v = _check(
            drug_name="Paracetamol",
            ingredients=["Paracetamol"],
            allergies=[AllergyInput("Penicilina")],
            classes=[_BETA_LACTAMS],
        )
        assert v.verdict == VERDICT_SAFE

    def test_allergen_not_in_class_no_cross(self):
        # Allergen outside the class even if the drug is in it → no cross.
        v = _check(
            drug_name="Cefalexina",
            ingredients=["Cefalexina"],
            allergies=[AllergyInput("Dipirona")],
            classes=[_BETA_LACTAMS],
        )
        assert v.verdict == VERDICT_SAFE
