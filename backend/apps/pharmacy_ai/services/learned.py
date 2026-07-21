"""
Learned demand-forecast model for the AI Farmácia (issue #131).

After 3+ months of dispensation history accrues in the pilot, a flat moving
average leaves money on the table: pharmacy demand has a strong *weekly* shape
(weekday peaks, weekend troughs) and a slow trend. This module fits a real,
**learned** time-series model — additive Holt-Winters (triple exponential
smoothing) with a weekly season — and only adopts it over the arithmetic
baseline when it actually wins a hold-out MAPE comparison.

Why Holt-Winters and not Prophet/ARIMA(statsmodels)?
    The production image installs from a hash-pinned, `--require-hashes` lockfile
    on a slim base. Prophet (cmdstanpy/stan) and statsmodels both drag in
    numpy/scipy/pandas — a heavy, compiler-bound tree that would have to be
    re-hashed and balloon the image. Holt-Winters is a classic seasonal model
    that fits in a few dozen lines of dependency-free Python, trains in
    milliseconds per drug, and is fully transparent/auditable — a better fit for
    this codebase's careful production posture. The seam (`forecast_demand`)
    isolates the algorithm, so a heavier learner can be swapped in later without
    touching the service or the REST contract.

Everything here is PURE: it takes a list of floats (a daily demand series,
oldest→newest, built by `timeseries.build_daily_demand`) and returns numbers.
No DB, no Django. That keeps it trivially unit-testable and leakage-free.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product

MODEL_VERSION = "hw-1.0.0"

# Model identifiers surfaced in the API so callers know which forecaster spoke.
MODEL_HOLT_WINTERS = "holt_winters_seasonal"
MODEL_BASELINE = "moving_average_baseline"

# Pharmacy demand is dominated by a weekly cycle; one season = 7 days.
DEFAULT_SEASON_LENGTH = 7

# Minimum full seasons of (post-trim) history required before we even attempt to
# train the seasonal model. Two seasons is the floor for estimating per-weekday
# indices; fewer and we stay on the baseline.
MIN_SEASONS_TO_TRAIN = 2

# Smoothing-parameter grid searched during fitting. Small and fixed → fast and
# deterministic (no RNG, reproducible forecasts). alpha=level, beta=trend,
# gamma=season.
_ALPHA_GRID = (0.1, 0.3, 0.5, 0.7, 0.9)
_BETA_GRID = (0.0, 0.1, 0.3)
_GAMMA_GRID = (0.1, 0.3, 0.5, 0.7)


# ─────────────────────────────────── metrics ────────────────────────────────


def mape(actual: list[float], predicted: list[float]) -> float | None:
    """
    Mean Absolute Percentage Error, as a percentage (e.g. 12.5 == 12.5%).

    Points where ``actual == 0`` are skipped — percentage error is undefined
    there (division by zero). Returns ``None`` when *every* actual is zero (no
    measurable demand to score against), which the caller reads as "cannot
    compare" and falls back to the baseline.
    """
    pairs = [(a, p) for a, p in zip(actual, predicted, strict=False) if a != 0]
    if not pairs:
        return None
    return 100.0 * sum(abs((a - p) / a) for a, p in pairs) / len(pairs)


# ─────────────────────────────────── baseline ───────────────────────────────


def moving_average_forecast(history: list[float], horizon: int) -> list[float]:
    """
    Arithmetic baseline: a flat forecast equal to the mean of ``history``,
    repeated ``horizon`` times. This is the same primitive the operator would
    reach for first, and the bar the learned model must beat.
    """
    if horizon <= 0:
        return []
    mean = sum(history) / len(history) if history else 0.0
    mean = max(0.0, mean)
    return [mean] * horizon


# ───────────────────────────── Holt-Winters (additive) ──────────────────────


@dataclass(frozen=True)
class _HWState:
    level: float
    trend: float
    seasonals: list[float]
    sse: float  # in-sample one-step-ahead sum of squared errors


def _hw_fit(series: list[float], m: int, alpha: float, beta: float, gamma: float) -> _HWState:
    """
    Fit additive Holt-Winters on ``series``. A partial trailing season is fine
    (initial level/trend/seasonals are seeded from the full seasons only).
    Returns the final smoothing state plus the in-sample one-step-ahead SSE used
    for parameter selection.
    """
    n = len(series)
    n_seasons = n // m

    # Seasonal averages per full season → initial level, trend, seasonal indices.
    season_avgs = [sum(series[s * m : (s + 1) * m]) / m for s in range(n_seasons)]
    level = season_avgs[0]
    trend = (season_avgs[1] - season_avgs[0]) / m if n_seasons >= 2 else 0.0

    seasonals = [0.0] * m
    for i in range(m):
        deviations = [series[s * m + i] - season_avgs[s] for s in range(n_seasons)]
        seasonals[i] = sum(deviations) / len(deviations)

    sse = 0.0
    for t in range(n):
        season = seasonals[t % m]
        # One-step-ahead prediction made *before* seeing series[t].
        prediction = level + trend + season
        error = series[t] - prediction
        sse += error * error

        last_level = level
        level = alpha * (series[t] - season) + (1 - alpha) * (last_level + trend)
        trend = beta * (level - last_level) + (1 - beta) * trend
        seasonals[t % m] = gamma * (series[t] - level) + (1 - gamma) * season

    return _HWState(level=level, trend=trend, seasonals=seasonals, sse=sse)


def _hw_forecast(state: _HWState, m: int, n: int, horizon: int) -> list[float]:
    """Project ``horizon`` steps from a fitted state; demand clamped at 0."""
    out = []
    for k in range(1, horizon + 1):
        season = state.seasonals[(n - 1 + k) % m]
        out.append(max(0.0, state.level + k * state.trend + season))
    return out


def _trim_leading_zeros(history: list[float]) -> list[float]:
    """
    Drop a leading run of zeros (e.g. a drug introduced part-way through the
    lookback window). A long zero prefix would otherwise drag the learned
    level/season toward zero on the cold-start and hand the comparison to the
    baseline unfairly.
    """
    first = next((i for i, v in enumerate(history) if v > 0), len(history))
    return history[first:]


def holt_winters_forecast(
    history: list[float], *, horizon: int, season_length: int = DEFAULT_SEASON_LENGTH
) -> list[float] | None:
    """
    Train additive Holt-Winters on ``history`` (grid-searching smoothing params
    to minimise in-sample one-step-ahead SSE) and forecast ``horizon`` days.

    Returns ``None`` when there is not enough post-trim history to estimate the
    weekly season (``< MIN_SEASONS_TO_TRAIN`` full seasons).
    """
    if horizon <= 0:
        return []

    series = _trim_leading_zeros(history)
    if len(series) < season_length * MIN_SEASONS_TO_TRAIN:
        return None

    best: _HWState | None = None
    for alpha, beta, gamma in product(_ALPHA_GRID, _BETA_GRID, _GAMMA_GRID):
        state = _hw_fit(series, season_length, alpha, beta, gamma)
        if best is None or state.sse < best.sse:
            best = state

    assert best is not None  # grid is non-empty
    return _hw_forecast(best, season_length, len(series), horizon)


# ─────────────────────────── hold-out evaluation / selection ─────────────────


@dataclass(frozen=True)
class AccuracyReport:
    """MAPE comparison of the learned model vs the arithmetic baseline."""

    model_version: str
    season_length: int
    holdout_days: int
    n_train: int
    mape_learned: float | None
    mape_baseline: float | None
    improved: bool  # learned strictly beat baseline on the hold-out

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ForecastResult:
    """Production forecast plus the accuracy that justified the model choice."""

    predictions: list[float]
    model: str
    season_length: int | None
    accuracy: AccuracyReport | None


def evaluate_models(
    history: list[float],
    *,
    holdout_days: int,
    season_length: int = DEFAULT_SEASON_LENGTH,
) -> AccuracyReport | None:
    """
    Back-test on a chronological hold-out: train on all but the last
    ``holdout_days`` days, forecast that tail, and score both models with MAPE.

    Returns ``None`` only when there is structurally too little history to form
    a train split with at least ``MIN_SEASONS_TO_TRAIN`` seasons after trimming.
    """
    series = _trim_leading_zeros(history)
    if holdout_days <= 0 or len(series) <= holdout_days:
        return None

    train = series[:-holdout_days]
    test = series[-holdout_days:]
    if len(train) < season_length * MIN_SEASONS_TO_TRAIN:
        return None

    baseline_pred = moving_average_forecast(train, holdout_days)
    learned_pred = holt_winters_forecast(train, horizon=holdout_days, season_length=season_length)

    mape_baseline = mape(test, baseline_pred)
    mape_learned = mape(test, learned_pred) if learned_pred is not None else None

    improved = (
        mape_learned is not None and mape_baseline is not None and mape_learned < mape_baseline
    )

    return AccuracyReport(
        model_version=MODEL_VERSION,
        season_length=season_length,
        holdout_days=holdout_days,
        n_train=len(train),
        mape_learned=mape_learned,
        mape_baseline=mape_baseline,
        improved=improved,
    )


def forecast_demand(
    history: list[float],
    *,
    horizon: int,
    holdout_days: int = DEFAULT_SEASON_LENGTH,
    season_length: int = DEFAULT_SEASON_LENGTH,
) -> ForecastResult:
    """
    Top-level entry point. Back-test the learned model against the baseline; if
    it wins the hold-out MAPE comparison, refit it on the *full* history and use
    it for the ``horizon``-day production forecast. Otherwise fall back to the
    arithmetic baseline. The endpoint always gets a usable forecast.
    """
    report = evaluate_models(history, holdout_days=holdout_days, season_length=season_length)

    if report is not None and report.improved:
        predictions = holt_winters_forecast(history, horizon=horizon, season_length=season_length)
        if predictions is not None:
            return ForecastResult(
                predictions=predictions,
                model=MODEL_HOLT_WINTERS,
                season_length=season_length,
                accuracy=report,
            )

    return ForecastResult(
        predictions=moving_average_forecast(history, horizon),
        model=MODEL_BASELINE,
        season_length=None,
        accuracy=report,
    )
