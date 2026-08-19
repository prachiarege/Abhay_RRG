"""Calculation-engine tests, including an independent reference implementation.

SRS 52.1 requires RRG values to be "validated against an independently calculated
reference dataset". `reference_rrg` below is that reference: a deliberately naive
NumPy implementation written from the specification in docs/RRG_CALCULATION_SPEC.md,
using explicit loops instead of pandas rolling windows. If the two agree to 1e-9 across
900 bars, the production implementation is doing what the spec says.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.params import RRGParams
from app.engine.quadrants import IMPROVING, LAGGING, LEADING, WEAKENING, classify
from app.engine.rrg_engine import (
    compute_rrg,
    relative_strength,
    rs_momentum_series,
    rs_ratio_series,
)

# Agreement tolerance between the two implementations. Not 1e-9: pandas computes rolling
# variance with a streaming (Welford-style) update while the reference below uses a naive
# two-pass sum, so the two accumulate float64 error in different orders. Measured worst
# case across 900 bars is ~1.1e-9 absolute on values of order 100, i.e. ~1e-11 relative,
# which is at the limit of double precision and some nine orders of magnitude below any
# financially meaningful difference.
TOLERANCE = 1e-8

# Must match _FLATNESS_EPSILON in app/engine/rrg_engine.py.
FLATNESS_EPSILON = 1e-12


# --------------------------------------------------------------------------------------
# Independent reference implementation -- plain loops, no pandas rolling machinery.
# --------------------------------------------------------------------------------------
def _sma(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if np.isnan(window).any():
            continue
        out[i] = window.mean()
    return out


def _sample_std(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if np.isnan(window).any():
            continue
        mean = window.mean()
        out[i] = np.sqrt(((window - mean) ** 2).sum() / (period - 1))
    return out


def _mean_abs(values: np.ndarray, period: int) -> np.ndarray:
    return _sma(np.abs(values), period)


def _standardise_ref(
    values: np.ndarray,
    numerator: np.ndarray,
    period: int,
    clip_sigma: float,
) -> np.ndarray:
    """Reference form of the rolling z-score, degenerate-variance rule included."""
    std = _sample_std(values, period)
    magnitude = _mean_abs(values, period)
    out = np.full(values.shape, np.nan)
    for i in range(len(values)):
        if np.isnan(numerator[i]) or np.isnan(std[i]) or np.isnan(magnitude[i]):
            continue
        floor = max(magnitude[i], 1.0) * FLATNESS_EPSILON
        if std[i] > floor:
            z = numerator[i] / std[i]
        elif abs(numerator[i]) <= floor:
            z = 0.0
        else:
            continue
        out[i] = max(-clip_sigma, min(clip_sigma, z))
    return out


def reference_rrg(
    sector: np.ndarray,
    benchmark: np.ndarray,
    p: RRGParams,
) -> tuple[np.ndarray, np.ndarray]:
    """RS-Ratio and RS-Momentum computed straight from the written specification."""
    rs = 100.0 * sector / benchmark

    smoothed = _sma(rs, p.smoothing_period) if p.smoothing_period > 1 else rs.copy()

    mean = _sma(smoothed, p.rs_period)
    z_ratio = _standardise_ref(smoothed, smoothed - mean, p.rs_period, p.clip_sigma)
    ratio = p.center + p.scale_factor * z_ratio

    raw = np.full(rs.shape, np.nan)
    for i in range(p.momentum_period, len(rs)):
        if np.isnan(ratio[i]) or np.isnan(ratio[i - p.momentum_period]):
            continue
        raw[i] = ratio[i] - ratio[i - p.momentum_period]

    z_momentum = _standardise_ref(raw, raw, p.norm_period, p.clip_sigma)
    momentum = p.center + p.scale_factor * z_momentum

    return ratio, momentum


# --------------------------------------------------------------------------------------


def test_matches_independent_reference(noisy_sector_series, benchmark_series, params):
    frame = compute_rrg(noisy_sector_series, benchmark_series, params)
    expected_ratio, expected_momentum = reference_rrg(
        noisy_sector_series.to_numpy(dtype="float64"),
        benchmark_series.to_numpy(dtype="float64"),
        params,
    )

    np.testing.assert_allclose(
        frame["rs_ratio"].to_numpy(dtype="float64"),
        expected_ratio,
        rtol=0,
        atol=TOLERANCE,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        frame["rs_momentum"].to_numpy(dtype="float64"),
        expected_momentum,
        rtol=0,
        atol=TOLERANCE,
        equal_nan=True,
    )


def test_reference_covers_all_four_quadrants(noisy_sector_series, benchmark_series, params):
    """The fixture must actually exercise every quadrant or the agreement proves little."""
    frame = compute_rrg(noisy_sector_series, benchmark_series, params)
    observed = set(frame["quadrant"].dropna().unique())
    assert observed == {LEADING, WEAKENING, LAGGING, IMPROVING}


def test_relative_strength_is_ratio(benchmark_series):
    sector = benchmark_series * 1.5
    rs = relative_strength(sector, benchmark_series)
    np.testing.assert_allclose(rs.dropna().to_numpy(), 150.0, atol=1e-9)


def test_relative_strength_guards_against_zero_benchmark():
    idx = pd.bdate_range("2024-01-01", periods=4)
    sector = pd.Series([100.0, 101.0, 102.0, 103.0], index=idx)
    benchmark = pd.Series([100.0, 0.0, -5.0, 100.0], index=idx)
    rs = relative_strength(sector, benchmark)
    assert np.isfinite(rs.iloc[0]) and np.isfinite(rs.iloc[3])
    assert rs.iloc[1:3].isna().all(), "zero/negative benchmark must yield NaN, not inf"


def test_momentum_sign_matches_ratio_direction(noisy_sector_series, benchmark_series, params):
    """SRS 8: above centre means positive momentum. Must hold on every single bar.

    This is the property that would break if RS-Momentum were de-meaned like RS-Ratio.
    """
    frame = compute_rrg(noisy_sector_series, benchmark_series, params)
    ratio = frame["rs_ratio"]
    momentum = frame["rs_momentum"]
    rose = ratio - ratio.shift(params.momentum_period)

    both = pd.DataFrame({"rose": rose, "momentum": momentum}).dropna()
    assert len(both) > 500, "fixture should leave plenty of comparable bars"

    above_centre = both["momentum"] > params.center
    actually_rose = both["rose"] > 0
    mismatches = (above_centre != actually_rose).sum()
    assert mismatches == 0, f"{mismatches} bars where momentum sign contradicted RS-Ratio"


def test_steady_outperformer_sits_right_of_centre_with_neutral_momentum(
    outperforming_series, benchmark_series, params
):
    """A constant performance edge means strength, but no ACCELERATION of strength.

    This sector beats the benchmark by the same margin every single bar. Its relative
    strength rises monotonically, so RS-Ratio must sit right of centre. But RS-Momentum
    measures the rate of change of RS-Ratio, and that rate is unchanging -- so momentum
    is exactly neutral. Reading a steady edge as "strong momentum" would be wrong.
    """
    frame = compute_rrg(outperforming_series, benchmark_series, params)
    ratio = frame["rs_ratio"].dropna()
    momentum = frame["rs_momentum"].dropna()

    assert len(ratio) > 100
    assert (ratio > params.center).all(), "monotonically strengthening RS must plot right"
    assert momentum.eq(params.center).all(), "an unchanging rate has neutral momentum"


def test_steady_underperformer_sits_left_of_centre(
    underperforming_series, benchmark_series, params
):
    """Mirror image of the outperformer: left of centre, momentum still neutral."""
    frame = compute_rrg(underperforming_series, benchmark_series, params)
    ratio = frame["rs_ratio"].dropna()
    momentum = frame["rs_momentum"].dropna()

    assert (ratio < params.center).all()
    assert momentum.eq(params.center).all()


def test_identical_series_plots_at_the_origin(benchmark_series, params):
    """A sector tracking the benchmark exactly belongs at (100, 100), not at NaN.

    Its RS is perfectly flat, so the rolling standard deviation is zero. The engine must
    resolve that as "no deviation from its own trend" -- the centre -- rather than either
    dividing by zero or discarding the sector from the chart.
    """
    frame = compute_rrg(benchmark_series.copy(), benchmark_series, params)
    assert frame["rs"].dropna().eq(100.0).all()

    ratio = frame["rs_ratio"].dropna()
    momentum = frame["rs_momentum"].dropna()
    assert len(ratio) > 0 and len(momentum) > 0
    assert ratio.eq(params.center).all()
    assert momentum.eq(params.center).all()
    assert np.isfinite(frame[["rs_ratio", "rs_momentum"]].to_numpy(dtype="float64")).any()


def test_degenerate_variance_never_yields_an_extreme(params):
    """The regression this guard exists for.

    A series that goes flat leaves a rolling standard deviation of floating-point dust.
    Dividing by dust would amplify the residue into a full clipped reading, reporting a
    sector as maximally weak precisely because nothing was happening to it.
    """
    idx = pd.bdate_range("2020-01-01", periods=400)
    benchmark = pd.Series(np.linspace(10_000.0, 12_000.0, 400), index=idx)
    sector = benchmark * 1.25  # exactly proportional -> perfectly flat RS
    frame = compute_rrg(sector, benchmark, params)

    for column in ("rs_ratio", "rs_momentum"):
        values = frame[column].dropna()
        assert values.eq(params.center).all(), (
            f"{column} drifted off centre on a flat series: "
            f"min={values.min()} max={values.max()}"
        )


def test_warmup_length_is_exact(noisy_sector_series, benchmark_series, params):
    """The first RS-Momentum value must land exactly on the documented warm-up bar."""
    frame = compute_rrg(noisy_sector_series, benchmark_series, params)
    momentum = frame["rs_momentum"]
    first_valid_position = momentum.to_numpy(dtype="float64", na_value=np.nan)
    first_index = int(np.argmax(np.isfinite(first_valid_position)))
    assert first_index == params.min_bars - 1, (
        f"first momentum value at bar {first_index + 1}, "
        f"but params.min_bars promises {params.min_bars}"
    )


def test_clipping_bounds_the_output(params):
    """A violent outlier must not fling a sector off the chart (SRS 8)."""
    idx = pd.bdate_range("2020-01-01", periods=200)
    benchmark = pd.Series(np.full(200, 10_000.0), index=idx)
    sector = pd.Series(np.full(200, 10_000.0), index=idx)
    sector.iloc[150:] = 90_000.0  # 9x overnight
    frame = compute_rrg(sector, benchmark, params)

    limit = params.center + params.scale_factor * params.clip_sigma
    floor = params.center - params.scale_factor * params.clip_sigma
    for column in ("rs_ratio", "rs_momentum"):
        values = frame[column].dropna()
        assert (values <= limit + 1e-9).all()
        assert (values >= floor - 1e-9).all()


def test_reproducibility_bitwise(noisy_sector_series, benchmark_series, params):
    """SRS 50.2: same inputs, same parameters, identical outputs."""
    first = compute_rrg(noisy_sector_series, benchmark_series, params)
    second = compute_rrg(noisy_sector_series, benchmark_series, params)
    pd.testing.assert_frame_equal(first, second)


def test_missing_sector_days_are_not_invented(benchmark_series, params):
    """A hole in the sector series must stay a hole, never be forward-filled (SRS 27)."""
    sector = benchmark_series * 1.1
    gap_dates = sector.index[300:305]
    sector = sector.drop(gap_dates)

    frame = compute_rrg(sector, benchmark_series, params)
    assert frame.loc[gap_dates, "rs"].isna().all()


def test_parameters_change_results(noisy_sector_series, benchmark_series):
    fast = compute_rrg(noisy_sector_series, benchmark_series, RRGParams(rs_period=8))
    slow = compute_rrg(noisy_sector_series, benchmark_series, RRGParams(rs_period=40))
    overlap = pd.DataFrame(
        {"fast": fast["rs_ratio"], "slow": slow["rs_ratio"]}
    ).dropna()
    assert len(overlap) > 100
    assert not np.allclose(overlap["fast"], overlap["slow"])


@pytest.mark.parametrize("bad", [{"rs_period": 1}, {"clip_sigma": 0}, {"scale_factor": -1}])
def test_invalid_parameters_rejected(bad):
    with pytest.raises(ValueError):
        RRGParams(**bad)


def test_fingerprint_is_parameter_sensitive():
    base = RRGParams()
    assert base.fingerprint() == RRGParams().fingerprint()
    assert base.fingerprint() != RRGParams(rs_period=20).fingerprint()
    assert len(base.fingerprint()) == 16


def test_quadrant_column_agrees_with_classify(noisy_sector_series, benchmark_series, params):
    frame = compute_rrg(noisy_sector_series, benchmark_series, params)
    for _, row in frame.dropna(subset=["rs_ratio", "rs_momentum"]).iterrows():
        assert row["quadrant"] == classify(
            row["rs_ratio"], row["rs_momentum"], params.center
        )
