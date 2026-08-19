"""Frequency conversion (SRS 5.2, 20, 28).

The SRS says weekly data must be "generated consistently using the selected weekly
convention" but never defines the convention. This module defines it:

*   A week runs Saturday through Friday (anchor ``W-FRI``), matching how NSE weekly
    candles are conventionally drawn.
*   The weekly observation is the LAST ACTUAL TRADING DAY'S close within the week,
    and the bar is labelled with that trading date -- not with the nominal Friday.
    A Friday holiday therefore yields a bar labelled Thursday, never a bar sitting
    on a non-trading day (SRS 28).
*   The in-progress week is EXCLUDED by default. Including it would make every
    sector's head point move a little every day, which reads as a bug to users and
    makes the tail non-reproducible.
"""

from __future__ import annotations

import pandas as pd

WEEK_ANCHOR = "W-FRI"


def normalise_daily(series: pd.Series) -> pd.Series:
    """Sort, drop duplicate dates (keeping the latest), and coerce to float."""
    s = series.astype("float64").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def to_weekly(
    series: pd.Series,
    include_partial: bool = False,
    anchor: str = WEEK_ANCHOR,
) -> pd.Series:
    """Collapse a daily series to weekly, labelled by last trading date in the week.

    Args:
        series: daily observations indexed by date.
        include_partial: keep the final, still-forming week. Default False.
        anchor: pandas weekly anchor defining where the week boundary falls.

    Returns:
        Weekly series indexed by real trading dates.
    """
    daily = normalise_daily(series).dropna()
    if daily.empty:
        return daily

    periods = daily.index.to_period(anchor)
    frame = pd.DataFrame(
        {"value": daily.to_numpy(), "date": daily.index},
        index=periods,
    )
    grouped = frame.groupby(level=0, sort=True).agg(
        value=("value", "last"), date=("date", "max")
    )

    if not include_partial and len(grouped) > 0:
        last_period = grouped.index[-1]
        # The final week is only complete once the calendar has moved past its end.
        # Conservative by design: in a week whose Friday is a holiday this defers the
        # bar until the next week opens, trading a one-week lag for a tail that never
        # rewrites itself.
        if last_period.end_time.normalize() > daily.index.max().normalize():
            grouped = grouped.iloc[:-1]

    if grouped.empty:
        return pd.Series(dtype="float64")

    out = pd.Series(
        grouped["value"].to_numpy(dtype="float64"),
        index=pd.DatetimeIndex(grouped["date"], name=daily.index.name),
    )
    return out.sort_index()


def to_frequency(
    series: pd.Series,
    frequency: str,
    include_partial: bool = False,
) -> pd.Series:
    """Dispatch to the requested frequency. Only daily and weekly ship in MVP."""
    if frequency == "daily":
        return normalise_daily(series)
    if frequency == "weekly":
        return to_weekly(series, include_partial=include_partial)
    raise ValueError(
        f"unsupported frequency {frequency!r}; supported: daily, weekly"
    )


def align_to_weekly_grid(
    sector_daily: pd.Series,
    benchmark_weekly: pd.Series,
    anchor: str = WEEK_ANCHOR,
) -> pd.Series:
    """Place a sector's weekly closes on the BENCHMARK's weekly labels.

    Resampling two series independently and then reindexing one onto the other does not
    work, and the failure is silent. Each series' weekly bar is labelled with its OWN last
    trading day, so a sector that is missing the benchmark's Friday gets labelled Thursday;
    the reindex then finds no match and yields NaN for a week where the sector in fact
    traded. With real feeds -- whose sector coverage is patchier than their index coverage
    -- this drops scattered weeks and leaves sectors plotted at stale dates.

    Matching on the week PERIOD instead pairs "the sector's last close that week" with
    "the benchmark's last close that week", which is what a weekly relative comparison
    means. A week where the sector genuinely has no observation still yields NaN, because
    that is a real gap rather than a labelling artefact.
    """
    empty = pd.Series(
        dtype="float64", index=benchmark_weekly.index, name=sector_daily.name
    )
    daily = normalise_daily(sector_daily).dropna()
    if daily.empty or benchmark_weekly.empty:
        return empty

    weekly_by_period = daily.groupby(daily.index.to_period(anchor)).last()
    target_periods = benchmark_weekly.index.to_period(anchor)
    values = weekly_by_period.reindex(target_periods)

    return pd.Series(
        values.to_numpy(dtype="float64"),
        index=benchmark_weekly.index,
        name=sector_daily.name,
    )
