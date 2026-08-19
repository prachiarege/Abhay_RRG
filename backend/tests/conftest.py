"""Shared fixtures. All synthetic data is deterministic -- seeded, never wall-clock."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.params import RRGParams

SEED = 20260819


def _business_days(n: int, start: str = "2020-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n, name="date")


@pytest.fixture(scope="session")
def rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


@pytest.fixture
def params() -> RRGParams:
    return RRGParams()


@pytest.fixture
def benchmark_series() -> pd.Series:
    """A benchmark on a steady upward drift with mild noise."""
    generator = np.random.default_rng(SEED)
    n = 900
    idx = _business_days(n)
    shocks = generator.normal(loc=0.0004, scale=0.008, size=n)
    values = 10_000.0 * np.exp(np.cumsum(shocks))
    return pd.Series(values, index=idx, name="benchmark")


@pytest.fixture
def outperforming_series(benchmark_series: pd.Series) -> pd.Series:
    """A sector that beats the benchmark by a steady margin every bar.

    Its relative strength therefore rises monotonically, which pins down what the
    engine must say about it: momentum above centre, and the point in the right half
    once the trend is established.
    """
    n = len(benchmark_series)
    edge = np.exp(np.cumsum(np.full(n, 0.0006)))
    return pd.Series(
        benchmark_series.to_numpy() * edge,
        index=benchmark_series.index,
        name="outperformer",
    )


@pytest.fixture
def underperforming_series(benchmark_series: pd.Series) -> pd.Series:
    n = len(benchmark_series)
    drag = np.exp(np.cumsum(np.full(n, -0.0006)))
    return pd.Series(
        benchmark_series.to_numpy() * drag,
        index=benchmark_series.index,
        name="underperformer",
    )


@pytest.fixture
def noisy_sector_series(benchmark_series: pd.Series) -> pd.Series:
    """A sector whose relative strength genuinely oscillates through all quadrants."""
    generator = np.random.default_rng(SEED + 1)
    n = len(benchmark_series)
    # A slow sine wave in log-relative space guarantees full rotation, plus noise so
    # the series is not pathologically smooth.
    cycle = 0.16 * np.sin(np.linspace(0, 6 * np.pi, n))
    noise = np.cumsum(generator.normal(0.0, 0.0015, size=n))
    return pd.Series(
        benchmark_series.to_numpy() * np.exp(cycle + noise),
        index=benchmark_series.index,
        name="cyclical",
    )
