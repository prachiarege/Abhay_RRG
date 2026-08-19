"""Data quality validation (SRS 27, 45).

Rule the SRS is explicit about and this module honours: never silently fill a missing
observation. Gaps are reported and left as gaps unless an interpolation policy is
explicitly requested.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date

import numpy as np
import pandas as pd

from .calendar import is_expected_non_trading_day

logger = logging.getLogger(__name__)

# A same-day move larger than this is treated as suspect rather than real. Indian
# sector indices have never moved this far in one session outside of a data error.
SPIKE_THRESHOLD_PCT = 25.0


@dataclass
class ValidationReport:
    symbol: str
    rows: int = 0
    duplicate_dates: list[str] = field(default_factory=list)
    missing_values: list[str] = field(default_factory=list)
    non_positive_values: list[str] = field(default_factory=list)
    weekend_or_holiday_rows: list[str] = field(default_factory=list)
    suspected_spikes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    first_date: str | None = None
    last_date: str | None = None

    @property
    def ok(self) -> bool:
        """Blocking problems only. Gaps and spikes are warnings, not failures."""
        return not (
            self.duplicate_dates or self.non_positive_values or self.rows == 0
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload

    def log(self) -> None:
        for stamp in self.missing_values:
            logger.warning("%s data unavailable for %s", self.symbol, stamp)
        for stamp in self.duplicate_dates:
            logger.error("%s duplicate observation for %s", self.symbol, stamp)
        for stamp in self.non_positive_values:
            logger.error("%s non-positive index value on %s", self.symbol, stamp)
        for stamp in self.suspected_spikes:
            logger.warning(
                "%s implausible single-session move on %s (>%.0f%%)",
                self.symbol,
                stamp,
                SPIKE_THRESHOLD_PCT,
            )
        for stamp in self.weekend_or_holiday_rows:
            logger.warning(
                "%s has a bar on %s, which is not an expected trading session",
                self.symbol,
                stamp,
            )


def _fmt(stamp) -> str:
    return pd.Timestamp(stamp).strftime("%Y-%m-%d")


def validate_price_series(
    series: pd.Series,
    symbol: str,
    expected_calendar: pd.DatetimeIndex | None = None,
) -> ValidationReport:
    """Check one price/index series for the defects listed in SRS 27.

    Args:
        series: observations indexed by date.
        symbol: for log lines and the report.
        expected_calendar: authoritative session dates (normally the benchmark's).
            When supplied, dates present here but absent from `series` are reported
            as gaps.
    """
    report = ValidationReport(symbol=symbol, rows=int(len(series)))
    if series.empty:
        logger.error("%s: no observations at all", symbol)
        return report

    idx = pd.DatetimeIndex(series.index).normalize()
    values = pd.Series(series.to_numpy(dtype="float64"), index=idx)

    duplicated = idx[idx.duplicated(keep="first")]
    report.duplicate_dates = sorted({_fmt(d) for d in duplicated})

    report.missing_values = [_fmt(d) for d in values.index[values.isna()]]

    finite = values.dropna()
    report.non_positive_values = [_fmt(d) for d in finite.index[finite <= 0]]

    report.weekend_or_holiday_rows = [
        _fmt(d) for d in values.index if is_expected_non_trading_day(d.date())
    ]

    positive = finite[finite > 0]
    if len(positive) > 1:
        pct_change = positive.pct_change().abs() * 100.0
        spikes = pct_change.index[pct_change > SPIKE_THRESHOLD_PCT]
        report.suspected_spikes = [_fmt(d) for d in spikes]

    if expected_calendar is not None and len(expected_calendar) > 0:
        expected = pd.DatetimeIndex(expected_calendar).normalize()
        # Only judge the window this series actually covers; a sector listed in 2020
        # is not "missing" all of 2015.
        window = expected[(expected >= values.index.min()) & (expected <= values.index.max())]
        missing = window.difference(values.dropna().index)
        report.gaps = [_fmt(d) for d in missing]

    report.first_date = _fmt(values.index.min())
    report.last_date = _fmt(values.index.max())
    return report


def usable_history(series: pd.Series, min_bars: int) -> bool:
    """Whether enough clean observations exist to produce any RRG value at all."""
    return int(series.dropna().shape[0]) >= min_bars


def coverage_summary(reports: list[ValidationReport]) -> dict:
    """Roll several reports into one payload for the ingestion log / admin view."""
    return {
        "symbols": len(reports),
        "clean": sum(1 for r in reports if r.ok),
        "with_warnings": sum(
            1 for r in reports if r.ok and (r.gaps or r.suspected_spikes or r.missing_values)
        ),
        "failed": [r.symbol for r in reports if not r.ok],
    }
