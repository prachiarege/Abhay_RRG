"""The no-look-ahead guarantee (SRS 21, 50.1) as an executable contract.

The property under test:

    The RRG point for date D computed from the FULL history must be identical to the
    RRG point for date D computed from history TRUNCATED at D.

If that fails, historical playback is lying: it would be showing positions that could
only have been known later, and every backtest built on this data would be optimistic.
This is the single most common way an RRG implementation goes quietly wrong, so it is
tested here across many dates rather than spot-checked.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.params import RRGParams
from app.engine.rrg_engine import compute_rrg


def _snapshot_at(sector, benchmark, cutoff, params):
    """Compute using only data available on or before `cutoff`."""
    truncated_sector = sector[sector.index <= cutoff]
    truncated_benchmark = benchmark[benchmark.index <= cutoff]
    frame = compute_rrg(truncated_sector, truncated_benchmark, params)
    return frame.loc[cutoff]


def test_truncation_invariance_across_many_dates(
    noisy_sector_series, benchmark_series, params
):
    full = compute_rrg(noisy_sector_series, benchmark_series, params)
    valid = full.dropna(subset=["rs_ratio", "rs_momentum"])
    assert len(valid) > 400

    # Sample across the whole valid range rather than only recent dates.
    sample_dates = valid.index[:: max(1, len(valid) // 40)]
    assert len(sample_dates) >= 20

    for cutoff in sample_dates:
        historical = _snapshot_at(noisy_sector_series, benchmark_series, cutoff, params)
        for column in ("rs", "rs_ratio", "rs_momentum"):
            assert historical[column] == pytest.approx(
                full.loc[cutoff, column], abs=1e-12
            ), f"{column} at {cutoff.date()} changed when future data was added"
        assert historical["quadrant"] == full.loc[cutoff, "quadrant"]


def test_quadrant_history_is_stable(noisy_sector_series, benchmark_series, params):
    """Quadrant assignments already made must never be rewritten by later data."""
    cutoff = noisy_sector_series.index[600]
    early = compute_rrg(
        noisy_sector_series[noisy_sector_series.index <= cutoff],
        benchmark_series[benchmark_series.index <= cutoff],
        params,
    )
    full = compute_rrg(noisy_sector_series, benchmark_series, params)

    overlap = early.dropna(subset=["rs_ratio"]).index
    pd.testing.assert_series_equal(
        early.loc[overlap, "quadrant"],
        full.loc[overlap, "quadrant"],
        check_names=False,
    )


def test_appending_one_bar_does_not_disturb_the_tail(
    noisy_sector_series, benchmark_series, params
):
    """Yesterday's plotted point must be exactly where it was before today arrived."""
    cutoff_position = 700
    sector_before = noisy_sector_series.iloc[:cutoff_position]
    bench_before = benchmark_series.iloc[:cutoff_position]
    sector_after = noisy_sector_series.iloc[: cutoff_position + 1]
    bench_after = benchmark_series.iloc[: cutoff_position + 1]

    before = compute_rrg(sector_before, bench_before, params)
    after = compute_rrg(sector_after, bench_after, params)

    shared = before.index
    for column in ("rs", "rs_ratio", "rs_momentum"):
        np.testing.assert_array_equal(
            before[column].to_numpy(dtype="float64", na_value=np.nan),
            after.loc[shared, column].to_numpy(dtype="float64", na_value=np.nan),
        )


def test_ema_smoothing_is_documented_as_approximate(
    noisy_sector_series, benchmark_series
):
    """EMA is offered but is NOT truncation-invariant -- this test pins that caveat down.

    An exponential average carries a seed that depends on where the input series starts,
    so recomputing a historical date from truncated data gives a slightly different
    answer. The deviation decays but never reaches zero. This is exactly why `sma` is
    the default, and why the docs warn against `ema` for reproducible historical work.
    """
    params = RRGParams(smoothing_method="ema")
    full = compute_rrg(noisy_sector_series, benchmark_series, params)
    valid = full.dropna(subset=["rs_ratio"])

    cutoff = valid.index[len(valid) // 2]
    historical = _snapshot_at(noisy_sector_series, benchmark_series, cutoff, params)

    # Close, because the seed's influence decays...
    assert historical["rs_ratio"] == pytest.approx(full.loc[cutoff, "rs_ratio"], abs=1e-6)
    # ...but the default remains SMA precisely because "close" is not "identical".
    assert RRGParams().smoothing_method == "sma"


def test_playback_snapshot_never_reads_future_bars(
    noisy_sector_series, benchmark_series, params
):
    """Corrupting the future must not change the past.

    A stronger form of the invariance test: rather than removing later data, replace it
    with garbage. Any accidental full-sample statistic would immediately show up.
    """
    cutoff_position = 500
    cutoff = noisy_sector_series.index[cutoff_position]

    poisoned_sector = noisy_sector_series.copy()
    poisoned_bench = benchmark_series.copy()
    poisoned_sector.iloc[cutoff_position + 1 :] *= 40.0
    poisoned_bench.iloc[cutoff_position + 1 :] *= 0.05

    clean = compute_rrg(noisy_sector_series, benchmark_series, params)
    poisoned = compute_rrg(poisoned_sector, poisoned_bench, params)

    up_to_cutoff = clean.index[clean.index <= cutoff]
    for column in ("rs", "rs_ratio", "rs_momentum"):
        np.testing.assert_array_equal(
            clean.loc[up_to_cutoff, column].to_numpy(dtype="float64", na_value=np.nan),
            poisoned.loc[up_to_cutoff, column].to_numpy(dtype="float64", na_value=np.nan),
        )
