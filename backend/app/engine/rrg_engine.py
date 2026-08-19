"""RRG calculation engine v1.0.0.

Implements the mathematics the SRS left as a placeholder ("100 + normalized(...)").
The full narrative specification lives in docs/RRG_CALCULATION_SPEC.md; this module
is the single normative implementation and must stay in agreement with it.

Design rules, in priority order:

1.  STRICT CAUSALITY. Every transform is a trailing rolling window or a backward
    shift. No operation may read a future bar. This is what makes historical
    playback (SRS 21) and the no-look-ahead requirement (SRS 50.1) true by
    construction rather than by convention.
2.  TRUNCATION INVARIANCE. With the default SMA smoothing, the value computed for
    date D from the full history is bit-identical to the value computed for D from
    history truncated at D. Enforced by tests/test_no_lookahead.py.
3.  MONOTONE MOMENTUM SEMANTICS. RS-Momentum > centre if and only if RS-Ratio is
    higher than it was `momentum_period` bars ago, satisfying SRS 8's requirement
    that "values above 100 represent positive momentum". Achieved by scaling the
    momentum difference without de-meaning it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .params import RRGParams
from .quadrants import classify, direction

__all__ = [
    "relative_strength",
    "moving_average",
    "rs_ratio_series",
    "rs_momentum_series",
    "compute_rrg",
    "align_series",
]


def align_series(sector: pd.Series, benchmark: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Align a sector to the benchmark's trading calendar.

    The benchmark defines the calendar (SRS 28): it is the series that must have an
    observation for a date to count as a trading day. A sector missing that date is
    left as NaN rather than being forward-filled, so gaps stay visible to validation
    instead of being silently invented (SRS 27).
    """
    benchmark = benchmark[~benchmark.index.duplicated(keep="last")].sort_index()
    sector = sector[~sector.index.duplicated(keep="last")].sort_index()
    aligned_sector = sector.reindex(benchmark.index)
    return aligned_sector, benchmark


def relative_strength(sector: pd.Series, benchmark: pd.Series) -> pd.Series:
    """RS = 100 * sector / benchmark (SRS 6.1).

    Scaled by 100 purely for readability; only the shape of the series matters.
    Non-positive benchmark values yield NaN rather than an infinity.
    """
    bench = benchmark.astype("float64")
    sect = sector.astype("float64")
    bench = bench.where(bench > 0)
    return 100.0 * (sect / bench)


def moving_average(series: pd.Series, period: int, method: str) -> pd.Series:
    """Causal moving average.

    `sma` is window-local and therefore truncation-invariant. `ema` is offered for
    users who want it but carries a start-dependent seed -- see RRGParams docstring.
    """
    s = series.astype("float64")
    if method == "none" or period <= 1:
        return s
    if method == "sma":
        return s.rolling(window=period, min_periods=period).mean()
    if method == "ema":
        return s.ewm(span=period, adjust=False, min_periods=period).mean()
    raise ValueError(f"unknown smoothing method: {method!r}")


# A rolling window whose spread is below this multiple of its own magnitude is treated
# as having no spread at all. Without a *relative* floor, a series that has genuinely
# gone flat leaves a rolling standard deviation of pure floating-point dust (~1e-15),
# and dividing by dust amplifies the residue into a full clipped +/-clip_sigma reading.
# That is how a sector with a perfectly steady performance edge would otherwise be
# reported as having maximal negative momentum.
_FLATNESS_EPSILON = 1e-12


def _standardise(
    values: pd.Series,
    window: int,
    clip_sigma: float,
    demean: bool,
) -> pd.Series:
    """Rolling z-score, clipped, with a scale-aware guard on degenerate variance.

    `demean=True`  -> (x - rolling_mean) / rolling_std, i.e. position relative to
                      the series' own recent trend. Used for RS-Ratio.
    `demean=False` -> x / rolling_std, preserving the sign of x. Used for
                      RS-Momentum so that positive momentum stays positive.

    Degenerate windows resolve as follows:

    *   spread negligible AND numerator negligible -> 0, i.e. the centre. A series that
        is not moving has no deviation from its own trend; that is a real answer, not a
        missing one. A sector tracking its benchmark exactly plots at (100, 100).
    *   spread negligible but numerator material -> NaN. There is no defensible scale
        to divide by, so the value is genuinely undefined rather than extreme.

    Never returns an infinity.
    """
    rolling = values.rolling(window=window, min_periods=window)
    sd = rolling.std(ddof=1)
    numerator = values - rolling.mean() if demean else values

    # Floor the flatness test to the magnitude of the data, never below 1.0, so the
    # epsilon is meaningful for both RS-Ratio (order 100) and momentum differences
    # (order 0.01 to a few units).
    magnitude = values.abs().rolling(window=window, min_periods=window).mean()
    floor = magnitude.clip(lower=1.0) * _FLATNESS_EPSILON

    usable = sd > floor
    z = (numerator / sd).where(usable)
    still = (~usable) & (numerator.abs() <= floor)
    z = z.mask(still, 0.0)
    return z.clip(lower=-clip_sigma, upper=clip_sigma)


def rs_ratio_series(rs: pd.Series, params: RRGParams) -> pd.Series:
    """RS-Ratio: normalised relative strength centred on `params.center` (SRS 7).

        rs_smooth = MA(rs, smoothing_period)
        z         = clip((rs_smooth - SMA(rs_smooth, rs_period)) / stdev(rs_smooth, rs_period))
        RS-Ratio  = center + scale_factor * z

    Interpretation: RS-Ratio > 100 means the sector's relative strength currently
    sits ABOVE its own `rs_period` trend -- it is outperforming on a trend-relative
    basis. This is the standard RRG reading, and it is why a sector can have beaten
    the benchmark over five years yet still plot left of centre today.
    """
    smoothed = moving_average(rs, params.smoothing_period, params.smoothing_method)
    z = _standardise(smoothed, params.rs_period, params.clip_sigma, demean=True)
    return params.center + params.scale_factor * z


def rs_momentum_series(ratio: pd.Series, params: RRGParams) -> pd.Series:
    """RS-Momentum: normalised rate of change of RS-Ratio (SRS 8).

        raw         = RS-Ratio - RS-Ratio shifted by momentum_period
        z           = clip(raw / stdev(raw, norm_period))
        RS-Momentum = center + scale_factor * z

    The raw difference is scaled but NOT de-meaned. That is deliberate: de-meaning
    would make "above 100" mean "rising faster than usual lately", whereas SRS 8
    requires it to mean "rising". Because stdev is strictly positive, sign(z) ==
    sign(raw), so RS-Momentum > centre exactly when RS-Ratio has risen over the
    lookback.
    """
    raw = ratio.diff(params.momentum_period)
    z = _standardise(raw, params.norm_period, params.clip_sigma, demean=False)
    return params.center + params.scale_factor * z


def compute_rrg(
    sector: pd.Series,
    benchmark: pd.Series,
    params: RRGParams | None = None,
) -> pd.DataFrame:
    """Full RRG series for one sector against one benchmark.

    Args:
        sector: close/index values indexed by date, ascending.
        benchmark: close/index values indexed by date, ascending.
        params: engine parameters; defaults to SRS 51 recommendations.

    Returns:
        DataFrame indexed by date with columns rs, rs_ratio, rs_momentum, quadrant,
        direction. Rows inside the warm-up window are present but carry NaN, so the
        caller can see exactly how much history was consumed.
    """
    params = params or RRGParams()
    aligned_sector, aligned_bench = align_series(sector, benchmark)

    rs = relative_strength(aligned_sector, aligned_bench)
    ratio = rs_ratio_series(rs, params)
    momentum = rs_momentum_series(ratio, params)

    frame = pd.DataFrame(
        {"rs": rs, "rs_ratio": ratio, "rs_momentum": momentum},
        index=aligned_bench.index,
    )

    frame["quadrant"] = [
        classify(r, m, params.center)
        for r, m in zip(frame["rs_ratio"], frame["rs_momentum"])
    ]

    dx = frame["rs_ratio"].diff()
    dy = frame["rs_momentum"].diff()
    frame["direction"] = [
        direction(x, y) if np.isfinite(x) and np.isfinite(y) else None
        for x, y in zip(dx.to_numpy(dtype="float64", na_value=np.nan),
                        dy.to_numpy(dtype="float64", na_value=np.nan))
    ]
    return frame
