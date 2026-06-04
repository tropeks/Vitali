"""NEWS2 — National Early Warning Score 2 (pure deterministic engine).

Implements the **public, validated** NEWS2 standard of the Royal College of
Physicians (RCP, 2017 update). This is the deterministic core of the clinical
deterioration wedge (``Observe→Predict→Intercept→Learn``): given a set of
vital signs it returns an aggregate early-warning score, a per-parameter
breakdown, and the RCP risk band that drives escalation.

Source: Royal College of Physicians. *National Early Warning Score (NEWS) 2:
Standardising the assessment of acute-illness severity in the NHS.* Updated
report of a working party. London: RCP, 2017.

Design constraints (mirror the dose/glosa/stockout engines):
- **PURE**: no DB, no clock, no LLM, no I/O. Deterministic function of inputs.
- **STRICT / no imputation**: NEWS2 requires all 7 parameters. If ANY is
  missing, the engine is **inert** (returns ``None``). Treating a missing
  parameter as "normal" (0) would silently under-score a deteriorating
  patient — e.g. an unrecorded respiratory rate of 25 (=3 points) would be
  read as 0 and could downgrade a high-risk patient to low risk.
- **advise/escalation only** — the orchestrator never blocks vitals recording.

The two SpO2 scales:
- **Scale 1** (default): the general population.
- **Scale 2**: patients with a prescribed target range of 88–92% (e.g. chronic
  hypercapnic respiratory failure / COPD). Misapplying Scale 2 masks hypoxia,
  so it is OFF by default and only enabled by an explicit per-patient clinical
  decision (``Patient.use_spo2_scale_2``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ENGINE_VERSION = "news2-rcp-2017-v1"

# Risk bands (RCP clinical-response thresholds).
BAND_LOW = "low"
BAND_LOW_MEDIUM = "low_medium"  # a single parameter scoring 3 ("red score")
BAND_MEDIUM = "medium"
BAND_HIGH = "high"

# Human-readable RCP clinical response per band (pt-BR).
CLINICAL_RESPONSE = {
    BAND_LOW: "Monitorização de rotina; reavaliação pela enfermagem.",
    BAND_LOW_MEDIUM: "Revisão urgente por clínico (escore 3 em parâmetro único).",
    BAND_MEDIUM: "Resposta urgente — avaliação por clínico registrado.",
    BAND_HIGH: "Resposta de emergência — avaliação por time de cuidados críticos.",
}

# The 7 parameters NEWS2 requires. Keys used in the breakdown dict.
PARAM_RESP_RATE = "respiratory_rate"
PARAM_SPO2 = "spo2"
PARAM_SUPP_O2 = "supplemental_oxygen"
PARAM_SYSTOLIC_BP = "systolic_bp"
PARAM_HEART_RATE = "heart_rate"
PARAM_TEMPERATURE = "temperature"
PARAM_CONSCIOUSNESS = "consciousness"

# ACVPU: only "A" (Alert) scores 0; new Confusion / Voice / Pain / Unresponsive
# all score 3. _VALID_ACVPU is the closed set the engine accepts — anything else
# (None, "", a stray letter from a fixture/import/admin write) is treated as a
# MISSING parameter → inert, never a phantom score.
_ALERT = "A"
_VALID_ACVPU = frozenset({"A", "C", "V", "P", "U"})


@dataclass(frozen=True)
class NEWS2Result:
    """Outcome of a NEWS2 evaluation.

    ``breakdown`` maps each of the 7 parameters to its sub-score so the
    orchestrator/UI can explain *why* the patient scored as they did.
    """

    score: int
    band: str
    breakdown: dict[str, int]
    any_param_three: bool
    clinical_response: str
    spo2_scale: int  # 1 or 2 — which SpO2 scale was applied
    engine_version: str = ENGINE_VERSION


def _score_respiratory_rate(rr: int) -> int:
    if rr <= 8:
        return 3
    if rr <= 11:  # 9–11
        return 1
    if rr <= 20:  # 12–20
        return 0
    if rr <= 24:  # 21–24
        return 2
    return 3  # >= 25


def _score_spo2_scale_1(spo2: int) -> int:
    if spo2 <= 91:
        return 3
    if spo2 <= 93:  # 92–93
        return 2
    if spo2 <= 95:  # 94–95
        return 1
    return 0  # >= 96


def _score_spo2_scale_2(spo2: int, on_oxygen: bool) -> int:
    """SpO2 Scale 2 (target 88–92%). On air, anything >= 93 scores 0; on
    supplemental oxygen, supranormal saturation is itself a warning sign."""
    if spo2 <= 83:
        return 3
    if spo2 <= 85:  # 84–85
        return 2
    if spo2 <= 87:  # 86–87
        return 1
    if spo2 <= 92:  # 88–92 (target range)
        return 0
    # spo2 >= 93
    if not on_oxygen:
        return 0
    if spo2 <= 94:  # 93–94 on oxygen
        return 1
    if spo2 <= 96:  # 95–96 on oxygen
        return 2
    return 3  # >= 97 on oxygen


def _score_supplemental_oxygen(on_oxygen: bool) -> int:
    return 2 if on_oxygen else 0


def _score_systolic_bp(sbp: int) -> int:
    if sbp <= 90:
        return 3
    if sbp <= 100:  # 91–100
        return 2
    if sbp <= 110:  # 101–110
        return 1
    if sbp <= 219:  # 111–219
        return 0
    return 3  # >= 220


def _score_heart_rate(hr: int) -> int:
    if hr <= 40:
        return 3
    if hr <= 50:  # 41–50
        return 1
    if hr <= 90:  # 51–90
        return 0
    if hr <= 110:  # 91–110
        return 1
    if hr <= 130:  # 111–130
        return 2
    return 3  # >= 131


def _score_temperature(temp: Decimal) -> int:
    # Boundaries are inclusive at the .0/.1 grid used by the RCP chart.
    if temp <= Decimal("35.0"):
        return 3
    if temp <= Decimal("36.0"):  # 35.1–36.0
        return 1
    if temp <= Decimal("38.0"):  # 36.1–38.0
        return 0
    if temp <= Decimal("39.0"):  # 38.1–39.0
        return 1
    return 2  # >= 39.1


def _score_consciousness(acvpu: str) -> int:
    return 0 if acvpu == _ALERT else 3


def _band(total: int, any_param_three: bool) -> str:
    if total >= 7:
        return BAND_HIGH
    if total >= 5:
        return BAND_MEDIUM
    if any_param_three:
        return BAND_LOW_MEDIUM
    return BAND_LOW


def compute_news2(
    *,
    respiratory_rate: int | None,
    spo2: int | None,
    on_supplemental_oxygen: bool | None,
    systolic_bp: int | None,
    heart_rate: int | None,
    temperature: Decimal | int | float | None,
    consciousness: str | None,
    use_spo2_scale_2: bool = False,
) -> NEWS2Result | None:
    """Compute the NEWS2 aggregate score from a set of vital signs.

    Returns ``None`` (inert) if **any** of the 7 required parameters is missing
    — NEWS2 must not be computed on a partial vitals set (see module docstring).

    ``temperature`` accepts Decimal/int/float and is normalised to Decimal so
    the .1°C boundary grid is honoured without float drift. ``consciousness``
    is the ACVPU letter (A/C/V/P/U).
    """
    # Strict completeness gate. Note: ``on_supplemental_oxygen`` is a tri-state
    # bool — None means *not recorded* (missing), while False is a valid reading
    # ("on air", scores 0). So we test identity against None, not truthiness.
    # The explicit or-chain (vs any(...)) lets the type-checker narrow each
    # parameter to non-None for the scoring calls below.
    if (
        respiratory_rate is None
        or spo2 is None
        or on_supplemental_oxygen is None
        or systolic_bp is None
        or heart_rate is None
        or temperature is None
        or consciousness is None
    ):
        return None
    # consciousness completeness is stricter than "not None": an empty string or
    # an invalid letter (e.g. from a fixture/import/admin write that bypasses the
    # serializer's ChoiceField) is ALSO treated as missing — never scored as +3.
    if consciousness not in _VALID_ACVPU:
        return None

    on_oxygen = bool(on_supplemental_oxygen)
    temp = temperature if isinstance(temperature, Decimal) else Decimal(str(temperature))

    if use_spo2_scale_2:
        spo2_points = _score_spo2_scale_2(spo2, on_oxygen)
        spo2_scale = 2
    else:
        spo2_points = _score_spo2_scale_1(spo2)
        spo2_scale = 1

    breakdown = {
        PARAM_RESP_RATE: _score_respiratory_rate(respiratory_rate),
        PARAM_SPO2: spo2_points,
        PARAM_SUPP_O2: _score_supplemental_oxygen(on_oxygen),
        PARAM_SYSTOLIC_BP: _score_systolic_bp(systolic_bp),
        PARAM_HEART_RATE: _score_heart_rate(heart_rate),
        PARAM_TEMPERATURE: _score_temperature(temp),
        PARAM_CONSCIOUSNESS: _score_consciousness(consciousness),
    }

    total = sum(breakdown.values())
    any_param_three = any(points == 3 for points in breakdown.values())
    band = _band(total, any_param_three)

    return NEWS2Result(
        score=total,
        band=band,
        breakdown=breakdown,
        any_param_three=any_param_three,
        clinical_response=CLINICAL_RESPONSE[band],
        spo2_scale=spo2_scale,
    )
