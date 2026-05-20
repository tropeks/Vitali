"""
Static question bank for the Triagem Inteligente primitive.

The bank lives in code (not data) on purpose for the v1 — the questions are
clinical decisions that need versioning and review, not user-editable
content. A future iteration can move the bank into a model + admin UI
without changing the FSM contract.

Question shape:
- `key`: stable identifier (used as the answer key in `TriageSession.red_flag_answers`).
- `prompt`: PT-BR text to send the patient (the WhatsApp / portal frontend
  reads this).
- `yes_is_red_flag`: when True, answering "sim" counts as a red flag; when
  False, it's the inverse (e.g. "Está acordado?" → answering "não" is the
  red flag).

The triage evaluator counts red-flag positives + applies a small set of
chief-complaint keywords to classify into routine / urgent / emergency.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TriageQuestion:
    key: str
    prompt: str
    yes_is_red_flag: bool = True


# The order matters — the FSM walks the bank top-to-bottom. Six is a
# defensible bedside-triage length: enough to catch the common red flags
# (Manchester / START heuristics) without exhausting a WhatsApp interaction.
RED_FLAG_QUESTIONS: tuple[TriageQuestion, ...] = (
    TriageQuestion(
        key="chest_pain",
        prompt=("Você está sentindo dor no peito agora? (responda 'sim' ou 'não')"),
    ),
    TriageQuestion(
        key="breathing_difficulty",
        prompt="Está com falta de ar ou dificuldade para respirar?",
    ),
    TriageQuestion(
        key="severe_bleeding",
        prompt="Há sangramento intenso ou que não para?",
    ),
    TriageQuestion(
        key="altered_consciousness",
        prompt="Você está consciente e orientado? (Se sim, responda 'sim')",
        yes_is_red_flag=False,
    ),
    TriageQuestion(
        key="severe_pain",
        prompt="Sua dor é forte (8 ou mais em 10)?",
    ),
    TriageQuestion(
        key="recent_trauma",
        prompt="Sofreu acidente ou trauma nas últimas 24 horas?",
    ),
)


# Chief-complaint keywords that elevate urgency on their own. Matching is
# case-insensitive substring search on the patient's free-text reply.
EMERGENCY_KEYWORDS: frozenset[str] = frozenset(
    {
        "dor no peito",
        "infarto",
        "avc",
        "derrame",
        "desmaio",
        "convulsão",
        "convulsao",
        "envenenamento",
        "intoxicação",
        "intoxicacao",
        "tentativa",  # tentativa de suicídio etc.
    }
)

URGENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "febre alta",
        "vômito",
        "vomito",
        "diarreia",
        "dor abdominal",
        "alergia",
        "queimadura",
    }
)


def question_by_key(key: str) -> TriageQuestion | None:
    for q in RED_FLAG_QUESTIONS:
        if q.key == key:
            return q
    return None


def question_keys() -> list[str]:
    return [q.key for q in RED_FLAG_QUESTIONS]
