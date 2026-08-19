"""Weekly resampling and trading-calendar tests (SRS 20, 28)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.calendar import (
    is_expected_non_trading_day,
    suspicious_sessions,
    trading_calendar,
)
from app.services.resample import normalise_daily, to_frequency, to_weekly


def _daily(dates: list[str], values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]))


def test_weekly_bar_is_labelled_with_the_last_trading_date():
    """A Friday holiday must produce a Thursday-labelled bar, not a Friday one (SRS 28)."""
    # Mon 6 Jan 2025 to Thu 9 Jan; Friday 10th absent, then the following full week.
    series = _daily(
        [
            "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09",
            "2025-01-13", "2025-01-14", "2025-01-15", "2025-01-16", "2025-01-17",
            "2025-01-20", "2025-01-21", "2025-01-22", "2025-01-23", "2025-01-24",
        ],
        [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113],
    )
    weekly = to_weekly(series)

    assert str(weekly.index[0].date()) == "2025-01-09", "week ending on a holiday Friday"
    assert weekly.iloc[0] == 103, "must take the last actual close of that week"
    assert str(weekly.index[1].date()) == "2025-01-17"
    assert weekly.iloc[1] == 108


def test_weekly_never_lands_on_a_weekend():
    index = pd.bdate_range("2024-01-01", periods=120)
    series = pd.Series(range(120), index=index, dtype="float64")
    weekly = to_weekly(series)
    assert all(stamp.weekday() < 5 for stamp in weekly.index)


def test_partial_week_excluded_by_default():
    """The in-progress week is dropped so the head point does not jitter daily."""
    # Full week to Fri 10 Jan, then a partial week Mon-Wed.
    series = _daily(
        [
            "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10",
            "2025-01-13", "2025-01-14", "2025-01-15",
        ],
        [100, 101, 102, 103, 104, 105, 106, 107],
    )
    without = to_weekly(series, include_partial=False)
    assert len(without) == 1
    assert str(without.index[-1].date()) == "2025-01-10"

    with_partial = to_weekly(series, include_partial=True)
    assert len(with_partial) == 2
    assert str(with_partial.index[-1].date()) == "2025-01-15"
    assert with_partial.iloc[-1] == 107


def test_adding_a_day_mid_week_does_not_move_completed_weeks():
    """Completed weekly bars must be stable as the current week fills in."""
    base = pd.bdate_range("2024-06-03", periods=25)
    series = pd.Series(range(25), index=base, dtype="float64")

    first = to_weekly(series)
    extended = pd.concat(
        [series, pd.Series([99.0], index=pd.DatetimeIndex([base[-1] + pd.Timedelta(days=1)]))]
    )
    second = to_weekly(extended)

    shared = first.index.intersection(second.index)
    pd.testing.assert_series_equal(first.loc[shared], second.loc[shared])


def test_duplicate_dates_keep_the_latest_value():
    series = _daily(["2025-01-06", "2025-01-06", "2025-01-07"], [100, 111, 102])
    cleaned = normalise_daily(series)
    assert len(cleaned) == 2
    assert cleaned.loc[pd.Timestamp("2025-01-06")] == 111


def test_unsorted_input_is_sorted():
    series = _daily(["2025-01-08", "2025-01-06", "2025-01-07"], [102, 100, 101])
    cleaned = normalise_daily(series)
    assert list(cleaned.index) == sorted(cleaned.index)


def test_daily_frequency_is_passthrough():
    index = pd.bdate_range("2024-01-01", periods=30)
    series = pd.Series(range(30), index=index, dtype="float64")
    assert len(to_frequency(series, "daily")) == 30


def test_unsupported_frequency_rejected():
    series = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp("2025-01-06")]))
    with pytest.raises(ValueError, match="unsupported frequency"):
        to_frequency(series, "monthly")


def test_empty_series_survives_resampling():
    empty = pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
    assert to_weekly(empty).empty


def test_fixed_holidays_recognised():
    assert is_expected_non_trading_day(pd.Timestamp("2025-01-26").date())  # Republic Day
    assert is_expected_non_trading_day(pd.Timestamp("2025-08-15").date())  # Independence
    assert is_expected_non_trading_day(pd.Timestamp("2025-10-02").date())  # Gandhi Jayanti
    assert not is_expected_non_trading_day(pd.Timestamp("2025-01-27").date())


def test_weekends_recognised():
    assert is_expected_non_trading_day(pd.Timestamp("2025-01-25").date())  # Saturday
    assert is_expected_non_trading_day(pd.Timestamp("2025-01-26").date())  # Sunday


def test_trading_calendar_derives_from_observed_dates():
    """The benchmark's own dates are authoritative, not a hard-coded table."""
    index = pd.DatetimeIndex(
        [pd.Timestamp(d) for d in ("2025-01-06", "2025-01-06", "2025-01-08", "2025-01-07")]
    )
    calendar = trading_calendar(index)
    assert len(calendar) == 3
    assert list(calendar) == sorted(calendar)


def test_suspicious_sessions_flags_a_saturday_bar():
    """Saturday sessions do occur in India (Budget day), so this is a warning, not a reject.

    2025-02-01 was a real special trading session for the Union Budget. The validator
    surfaces it for a human to confirm rather than discarding the bar, which is the right
    default when the holiday table cannot know about special sessions.
    """
    index = pd.DatetimeIndex(
        [pd.Timestamp("2025-01-31"), pd.Timestamp("2025-02-01"), pd.Timestamp("2025-02-03")]
    )
    flagged = suspicious_sessions(index)
    assert pd.Timestamp("2025-02-01").date() in flagged
    assert pd.Timestamp("2025-01-31").date() not in flagged


# --------------------------------------------------------- benchmark weekly-grid alignment


def test_sector_missing_the_benchmark_friday_still_aligns():
    """Regression: independently-resampled weekly labels silently dropped whole weeks.

    The benchmark trades Mon-Fri. The sector is missing Friday but traded Thursday. Both
    series therefore have an observation for that week, but resampling each on its own
    labels one bar Friday and the other Thursday, and a reindex then finds no match --
    producing NaN for a week in which the sector demonstrably traded.
    """
    from app.services.resample import align_to_weekly_grid

    benchmark_daily = _daily(
        ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"],
        [200, 201, 202, 203, 204],
    )
    sector_daily = _daily(
        ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"],
        [100, 101, 102, 103],
    )
    benchmark_weekly = to_weekly(benchmark_daily, include_partial=True)
    assert str(benchmark_weekly.index[-1].date()) == "2025-01-10"

    # The naive approach loses the week entirely.
    naive = to_weekly(sector_daily, include_partial=True).reindex(benchmark_weekly.index)
    assert naive.isna().all()

    # Period-matched alignment keeps the sector's own Thursday close on the Friday label.
    aligned = align_to_weekly_grid(sector_daily, benchmark_weekly)
    assert list(aligned.index) == list(benchmark_weekly.index)
    assert aligned.iloc[-1] == 103


def test_weekly_grid_preserves_genuine_gaps():
    """A week where the sector truly did not trade must stay NaN, not be carried forward."""
    from app.services.resample import align_to_weekly_grid

    benchmark_daily = _daily(
        [
            "2025-01-06", "2025-01-10",
            "2025-01-13", "2025-01-17",
            "2025-01-20", "2025-01-24",
        ],
        [200, 201, 202, 203, 204, 205],
    )
    # The sector skips the middle week completely.
    sector_daily = _daily(
        ["2025-01-06", "2025-01-10", "2025-01-20", "2025-01-24"],
        [100, 101, 104, 105],
    )
    benchmark_weekly = to_weekly(benchmark_daily, include_partial=True)
    aligned = align_to_weekly_grid(sector_daily, benchmark_weekly)

    assert len(aligned) == 3
    assert aligned.iloc[0] == 101
    assert pd.isna(aligned.iloc[1]), "a real gap must remain a gap"
    assert aligned.iloc[2] == 105


def test_weekly_grid_handles_empty_sector():
    from app.services.resample import align_to_weekly_grid

    benchmark_weekly = to_weekly(
        _daily(["2025-01-06", "2025-01-10"], [200, 201]), include_partial=True
    )
    empty = pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
    aligned = align_to_weekly_grid(empty, benchmark_weekly)
    assert len(aligned) == len(benchmark_weekly)
    assert aligned.isna().all()
