"""Quadrant transition detection and centre-line crossings (SRS 23, 24)."""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from .quadrants import rotation_signal


@dataclass(frozen=True)
class RotationEvent:
    date: str
    symbol: str
    previous_quadrant: str
    current_quadrant: str
    signal: str
    rs_ratio: float
    rs_momentum: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CrossingEvent:
    date: str
    symbol: str
    metric: str
    kind: str
    value: float

    def to_dict(self) -> dict:
        return asdict(self)


def detect_rotations(frame: pd.DataFrame, symbol: str) -> list[RotationEvent]:
    """Find every quadrant change in an RRG series.

    Only consecutive rows that both carry a known quadrant count. A gap in the data
    does not manufacture a transition when values resume on the far side of it.
    """
    events: list[RotationEvent] = []
    previous_quadrant: str | None = None
    for date, quadrant in frame["quadrant"].items():
        if not isinstance(quadrant, str):
            continue
        signal = rotation_signal(previous_quadrant, quadrant)
        if signal is not None:
            events.append(
                RotationEvent(
                    date=pd.Timestamp(date).strftime("%Y-%m-%d"),
                    symbol=symbol,
                    previous_quadrant=previous_quadrant,
                    current_quadrant=quadrant,
                    signal=signal,
                    rs_ratio=round(float(frame.loc[date, "rs_ratio"]), 4),
                    rs_momentum=round(float(frame.loc[date, "rs_momentum"]), 4),
                )
            )
        previous_quadrant = quadrant
    return events


def detect_crossings(
    frame: pd.DataFrame,
    symbol: str,
    center: float = 100.0,
) -> list[CrossingEvent]:
    """Find RS-Ratio / RS-Momentum crossings of the centre line (SRS 24, alerts 3 & 4)."""
    events: list[CrossingEvent] = []
    for metric in ("rs_ratio", "rs_momentum"):
        series = frame[metric].dropna()
        if len(series) < 2:
            continue
        above = series >= center
        flips = above.ne(above.shift())
        flips.iloc[0] = False
        for date in series.index[flips.to_numpy()]:
            events.append(
                CrossingEvent(
                    date=pd.Timestamp(date).strftime("%Y-%m-%d"),
                    symbol=symbol,
                    metric=metric,
                    kind="crossed_above" if bool(above.loc[date]) else "crossed_below",
                    value=round(float(series.loc[date]), 4),
                )
            )
    return events
