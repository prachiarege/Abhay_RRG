"""Relative performance statistics and the composite rotation score."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Calendar offsets rather than bar counts, so the same definitions hold for daily
# and weekly series (SRS 25). "1d" on a weekly series resolves to the previous
# weekly bar, which is the only honest answer.
RETURN_WINDOWS: dict[str, pd.DateOffset] = {
    "1d": pd.DateOffset(days=1),
    "1w": pd.DateOffset(weeks=1),
    "1m": pd.DateOffset(months=1),
    "3m": pd.DateOffset(months=3),
    "6m": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
}


def _value_on_or_before(series: pd.Series, when: pd.Timestamp) -> float | None:
    """Last non-null observation at or before `when`. Strictly backward-looking."""
    clean = series.dropna()
    if clean.empty:
        return None
    idx = clean.index.searchsorted(when, side="right") - 1
    if idx < 0:
        return None
    value = float(clean.iloc[idx])
    return value if np.isfinite(value) and value > 0 else None


def relative_return(
    sector: pd.Series,
    benchmark: pd.Series,
    as_of: pd.Timestamp,
    offset: pd.DateOffset,
) -> float | None:
    """Geometric relative return, in percent.

        (sector_growth / benchmark_growth - 1) * 100

    The SRS gives this as an arithmetic difference of returns (section 25) while
    displaying it as a percentage of relative performance (sections 14, 18). The two
    diverge materially over 6M/1Y horizons, and only one of them can match the
    export (SRS 52.8), so the geometric form is used consistently everywhere.
    """
    start = as_of - offset
    s_now = _value_on_or_before(sector, as_of)
    s_then = _value_on_or_before(sector, start)
    b_now = _value_on_or_before(benchmark, as_of)
    b_then = _value_on_or_before(benchmark, start)
    if None in (s_now, s_then, b_now, b_then):
        return None
    sector_growth = s_now / s_then
    bench_growth = b_now / b_then
    if bench_growth <= 0:
        return None
    return (sector_growth / bench_growth - 1.0) * 100.0


def relative_returns(
    sector: pd.Series,
    benchmark: pd.Series,
    as_of: pd.Timestamp,
    windows: dict[str, pd.DateOffset] | None = None,
) -> dict[str, float | None]:
    windows = windows or RETURN_WINDOWS
    return {
        label: relative_return(sector, benchmark, as_of, offset)
        for label, offset in windows.items()
    }


@dataclass(frozen=True)
class ScoreWeights:
    """Weights for the composite rotation score (SRS 26). Must sum to 1.0."""

    rs_ratio: float = 0.40
    rs_momentum: float = 0.40
    momentum_change: float = 0.20

    def __post_init__(self) -> None:
        total = self.rs_ratio + self.rs_momentum + self.momentum_change
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"rotation score weights must sum to 1.0, got {total}")


def _percentile_rank(values: dict[str, float | None]) -> dict[str, float | None]:
    """Rank each key's value within the universe, scaled 0-100.

    Ties share the average rank. A universe of one scores 50 (neutral), because a
    percentile has no meaning without peers.
    """
    present = {k: v for k, v in values.items() if v is not None and np.isfinite(v)}
    if not present:
        return dict.fromkeys(values, None)
    if len(present) == 1:
        only = next(iter(present))
        return {k: (50.0 if k == only else None) for k in values}
    ranked = pd.Series(present).rank(method="average", pct=True) * 100.0
    return {k: (float(ranked[k]) if k in ranked.index else None) for k in values}


def rotation_scores(
    latest: dict[str, dict[str, float | None]],
    weights: ScoreWeights | None = None,
) -> dict[str, float | None]:
    """Composite score per sector, 0-100.

    Args:
        latest: {symbol: {"rs_ratio": x, "rs_momentum": y, "momentum_change": d}}
        weights: component weights.

    Caveat worth surfacing in the UI: because the components are percentile ranks
    WITHIN the selected universe, scores are not comparable across different sector
    selections -- adding or removing a sector shifts everyone else's score. The score
    is supplementary and never replaces the underlying RS values (SRS 26).
    """
    weights = weights or ScoreWeights()
    ratio_ranks = _percentile_rank({k: v.get("rs_ratio") for k, v in latest.items()})
    mom_ranks = _percentile_rank({k: v.get("rs_momentum") for k, v in latest.items()})
    change_ranks = _percentile_rank(
        {k: v.get("momentum_change") for k, v in latest.items()}
    )

    out: dict[str, float | None] = {}
    for symbol in latest:
        parts = (
            (ratio_ranks.get(symbol), weights.rs_ratio),
            (mom_ranks.get(symbol), weights.rs_momentum),
            (change_ranks.get(symbol), weights.momentum_change),
        )
        if any(value is None for value, _ in parts):
            out[symbol] = None
            continue
        out[symbol] = round(sum(value * weight for value, weight in parts), 2)
    return out
