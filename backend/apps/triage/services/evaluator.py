"""
Triage urgency evaluator.

Given a chief-complaint string and a `{question_key: "sim"|"não"}` answer
map, classify the session as `routine | urgent | emergency`. The rules
are intentionally explicit (no ML, no scoring magic) so:

- Audit: a clinician can hand-trace why a given session was escalated.
- Test: every rule is unit-testable in isolation.
- Swap: a future iteration with an LLM-backed classifier can replace
  `evaluate` while keeping the input/output shape.

Rules (top-down precedence):
1. Any chief-complaint keyword in `EMERGENCY_KEYWORDS` → `emergency`.
2. ≥2 red flags positive OR `severe_bleeding` positive OR
   `altered_consciousness` negative (which means the patient said "no, I'm
   not oriented") → `emergency`.
3. Any chief-complaint keyword in `URGENT_KEYWORDS` OR exactly 1 red flag
   positive → `urgent`.
4. Otherwise → `routine`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .question_bank import (
    EMERGENCY_KEYWORDS,
    RED_FLAG_QUESTIONS,
    URGENT_KEYWORDS,
    question_by_key,
)

URGENCY_ROUTINE = "routine"
URGENCY_URGENT = "urgent"
URGENCY_EMERGENCY = "emergency"


@dataclass(frozen=True)
class TriageDecision:
    urgency: str
    red_flags_positive: int
    matched_keywords: list[str]
    rationale: str

    def to_dict(self) -> dict:
        return {
            "urgency": self.urgency,
            "red_flags_positive": self.red_flags_positive,
            "matched_keywords": list(self.matched_keywords),
            "rationale": self.rationale,
        }


def evaluate(chief_complaint: str, answers: dict[str, str]) -> TriageDecision:
    """Return a `TriageDecision` for the given complaint + answers.

    `answers` keys must match `TriageQuestion.key`. Values are "sim" / "não"
    (case-insensitive; trailing whitespace ignored). Missing or unrecognised
    answers are treated as "não" — the system errs on the side of NOT
    escalating without evidence.
    """
    text = (chief_complaint or "").lower().strip()
    matched = _match_keywords(text)
    positives, key_red_flags = _count_red_flags(answers)

    if "emergency_keyword" in matched:
        return TriageDecision(
            urgency=URGENCY_EMERGENCY,
            red_flags_positive=positives,
            matched_keywords=[kw for kw in matched if kw != "emergency_keyword"],
            rationale="Chief-complaint contains an emergency keyword.",
        )

    if (
        positives >= 2
        or "severe_bleeding" in key_red_flags
        or "altered_consciousness" in key_red_flags
    ):
        return TriageDecision(
            urgency=URGENCY_EMERGENCY,
            red_flags_positive=positives,
            matched_keywords=list(matched),
            rationale=(
                "Multiple red flags or critical single red flag "
                "(sangramento intenso / consciência alterada)."
            ),
        )

    if "urgent_keyword" in matched or positives == 1:
        return TriageDecision(
            urgency=URGENCY_URGENT,
            red_flags_positive=positives,
            matched_keywords=[kw for kw in matched if kw != "urgent_keyword"],
            rationale="One red flag or an urgent chief-complaint keyword.",
        )

    return TriageDecision(
        urgency=URGENCY_ROUTINE,
        red_flags_positive=0,
        matched_keywords=[],
        rationale="No red flags or urgent keywords detected.",
    )


def _match_keywords(text: str) -> list[str]:
    out: list[str] = []
    for kw in EMERGENCY_KEYWORDS:
        if kw in text:
            out.append(kw)
            out.append("emergency_keyword")
            break  # one is enough to trigger
    for kw in URGENT_KEYWORDS:
        if kw in text:
            out.append(kw)
            out.append("urgent_keyword")
            break
    return out


def _count_red_flags(answers: dict[str, str]) -> tuple[int, list[str]]:
    """Return (count, list_of_question_keys_that_were_red_flagged)."""
    positives = 0
    keys: list[str] = []
    for q in RED_FLAG_QUESTIONS:
        raw = (answers.get(q.key) or "").strip().lower()
        is_sim = raw in {"sim", "s", "yes", "y", "true", "1"}
        # `yes_is_red_flag=False` flips the polarity (e.g. "está consciente?").
        red = is_sim if q.yes_is_red_flag else not is_sim and bool(raw)
        if red:
            positives += 1
            keys.append(q.key)
        # If the question key is missing entirely, do NOT count it (default
        # to "no evidence"). The FSM ensures every question is answered
        # before evaluation; this is defensive.
        _ = question_by_key  # keep reference live for type-checkers
    return positives, keys
