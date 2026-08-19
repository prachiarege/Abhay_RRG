"""RRG orchestration: prices in, chart payload out.

The look-ahead-safety rule lives here and is worth stating plainly, because it is the
one place where a plausible-looking refactor would silently break the product:

    Series are TRUNCATED AT `as_of` BEFORE the engine is called -- never computed on full
    history and sliced afterwards.

With the engine's finite-window transforms the two happen to agree today, which is
exactly why the ordering must be deliberate rather than incidental: the moment anyone
introduces a full-sample statistic, truncate-then-compute still tells the truth while
compute-then-slice starts leaking the future into the past.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..config import get_settings
from ..engine.params import ENGINE_VERSION, RRGParams
from ..engine.quadrants import heading_label
from ..engine.rotation import detect_rotations
from ..engine.rrg_engine import compute_rrg
from ..engine.stats import RETURN_WINDOWS, ScoreWeights, relative_returns, rotation_scores
from ..models import Benchmark, Sector
from .cache import cache_key, get_cache
from .ingestion import load_close_series
from .resample import align_to_weekly_grid, to_frequency

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RRGRequest:
    benchmark: str
    frequency: str = "weekly"
    sectors: tuple[str, ...] = ()
    as_of: date | None = None
    tail_length: int = 10
    params: RRGParams = field(default_factory=RRGParams)
    include_partial: bool = False

    def cache_signature(self) -> str:
        return cache_key(
            "rrg",
            self.benchmark,
            self.frequency,
            ",".join(sorted(self.sectors)),
            self.as_of.isoformat() if self.as_of else "latest",
            self.tail_length,
            self.include_partial,
            self.params.fingerprint(),
        )


class InsufficientHistory(ValueError):
    """Raised when the requested window cannot support the requested parameters.

    Deliberately an error rather than a silent shortening. SRS 51 defaults to a 1-year
    display history while SRS 9 allows a 60-period tail; on weekly data that combination
    needs roughly two years of bars before the first point even exists. Quietly returning
    a stub tail would look like a working chart that happens to be wrong.
    """


def _rounded(value, digits: int = 4):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(number) else round(number, digits)


def _series_for(
    session: Session,
    symbol: str,
    frequency: str,
    as_of: date | None,
    include_partial: bool,
    weekly_grid: pd.Series | None = None,
) -> pd.Series:
    """Load, TRUNCATE, then resample. Order matters -- see the module docstring.

    `weekly_grid` is the benchmark's already-resampled weekly series. When supplied (for
    sectors, on weekly frequency) the sector is placed on the benchmark's week labels
    rather than resampled independently -- see `align_to_weekly_grid` for why independent
    resampling silently drops weeks.
    """
    daily = load_close_series(session, symbol, end=as_of)
    if daily.empty:
        return daily
    if frequency == "weekly" and weekly_grid is not None:
        return align_to_weekly_grid(daily, weekly_grid)
    return to_frequency(daily, frequency, include_partial=include_partial)


def build_rrg(
    session: Session,
    request: RRGRequest,
    sector_rows: list[Sector] | None = None,
    benchmark_row: Benchmark | None = None,
    use_cache: bool = True,
) -> dict:
    """Assemble the full RRG payload for one request.

    Returns a dict shaped per SRS 34, extended with the diagnostics the UI needs
    (warm-up requirements, per-sector failures, score caveats).
    """
    cache = get_cache()
    signature = request.cache_signature()
    if use_cache:
        cached = cache.get(signature)
        if cached is not None:
            return cached

    from sqlalchemy import select

    if benchmark_row is None:
        benchmark_row = session.scalar(
            select(Benchmark).where(Benchmark.symbol == request.benchmark)
        )
    if benchmark_row is None:
        raise ValueError(f"unknown benchmark: {request.benchmark}")

    # Sectors the caller asked for but which cannot be plotted. Populated here for
    # explicitly-requested symbols and extended below for data-level failures, so the
    # response always accounts for every symbol the caller named.
    unavailable: list[dict] = []

    if sector_rows is None:
        if request.sectors:
            # An explicitly requested symbol is looked up regardless of `active`, so that
            # an inactive or unknown selection is REPORTED rather than silently dropped.
            # Quietly returning fewer sectors than were asked for reads as a broken chart.
            found = {
                row.symbol: row
                for row in session.scalars(
                    select(Sector).where(Sector.symbol.in_(request.sectors))
                )
            }
            sector_rows = []
            for symbol in request.sectors:
                row = found.get(symbol)
                if row is None:
                    unavailable.append(
                        {"symbol": symbol, "name": symbol, "reason": "unknown sector"}
                    )
                elif not row.active:
                    unavailable.append(
                        {
                            "symbol": row.symbol,
                            "name": row.display_name,
                            "reason": "sector is inactive for the configured data provider",
                        }
                    )
                else:
                    sector_rows.append(row)
            sector_rows.sort(key=lambda s: s.sort_order)
        else:
            sector_rows = list(
                session.scalars(
                    select(Sector)
                    .where(Sector.active.is_(True), Sector.is_default.is_(True))
                    .order_by(Sector.sort_order)
                )
            )

    if not sector_rows:
        detail = "; ".join(f"{u['symbol']}: {u['reason']}" for u in unavailable)
        raise ValueError(f"no plottable sectors selected{': ' + detail if detail else ''}")

    benchmark_series = _series_for(
        session,
        benchmark_row.symbol,
        request.frequency,
        request.as_of,
        request.include_partial,
    )
    if benchmark_series.empty:
        raise InsufficientHistory(
            f"no stored price data for benchmark {benchmark_row.symbol}. "
            "Run a data refresh first."
        )

    params = request.params
    required_bars = params.min_bars + request.tail_length - 1
    if len(benchmark_series) < required_bars:
        raise InsufficientHistory(
            f"{request.frequency} history for {benchmark_row.symbol} has "
            f"{len(benchmark_series)} bars, but a {request.tail_length}-period tail with "
            f"rs_period={params.rs_period}, momentum_period={params.momentum_period}, "
            f"smoothing_period={params.smoothing_period} needs {required_bars} "
            f"({params.min_bars} for warm-up + {request.tail_length - 1} for the tail). "
            "Ingest more history, shorten the tail, or reduce the periods."
        )

    sectors_payload: list[dict] = []
    latest_components: dict[str, dict[str, float | None]] = {}
    frames: dict[str, pd.DataFrame] = {}
    as_of_effective: pd.Timestamp | None = None

    for sector in sector_rows:
        sector_series = _series_for(
            session,
            sector.symbol,
            request.frequency,
            request.as_of,
            request.include_partial,
            weekly_grid=benchmark_series,
        )
        if sector_series.empty:
            unavailable.append(
                {
                    "symbol": sector.symbol,
                    "name": sector.display_name,
                    "reason": "no stored price data",
                }
            )
            continue

        try:
            frame = compute_rrg(sector_series, benchmark_series, params)
        except Exception as exc:  # noqa: BLE001
            # One sector's failure must not take down the chart (SRS 46).
            logger.exception("RRG computation failed for %s", sector.symbol)
            unavailable.append(
                {
                    "symbol": sector.symbol,
                    "name": sector.display_name,
                    "reason": f"calculation error: {exc}",
                }
            )
            continue

        valid = frame.dropna(subset=["rs_ratio", "rs_momentum"])
        if valid.empty:
            unavailable.append(
                {
                    "symbol": sector.symbol,
                    "name": sector.display_name,
                    "reason": (
                        f"insufficient overlapping history "
                        f"({len(sector_series)} bars, needs {params.min_bars})"
                    ),
                }
            )
            continue

        frames[sector.symbol] = frame
        tail = valid.tail(request.tail_length)
        head = tail.iloc[-1]
        head_date = pd.Timestamp(tail.index[-1])
        as_of_effective = head_date if as_of_effective is None else max(as_of_effective, head_date)

        previous_quadrant = None
        if len(valid) > len(tail) or len(tail) > 1:
            position = valid.index.get_loc(tail.index[-1])
            if isinstance(position, int) and position > 0:
                previous_quadrant = valid.iloc[position - 1]["quadrant"]

        momentum_change = None
        if len(valid) >= 2:
            momentum_change = float(
                valid["rs_momentum"].iloc[-1] - valid["rs_momentum"].iloc[-2]
            )

        latest_components[sector.symbol] = {
            "rs_ratio": float(head["rs_ratio"]),
            "rs_momentum": float(head["rs_momentum"]),
            "momentum_change": momentum_change,
        }

        returns = relative_returns(
            sector_series, benchmark_series, head_date, RETURN_WINDOWS
        )

        sectors_payload.append(
            {
                "symbol": sector.symbol,
                "name": sector.display_name,
                "short_name": sector.short_name,
                "full_name": sector.sector_name,
                "color": sector.color,
                "rs_ratio": _rounded(head["rs_ratio"]),
                "rs_momentum": _rounded(head["rs_momentum"]),
                "quadrant": head["quadrant"],
                "previous_quadrant": previous_quadrant,
                "direction": head["direction"],
                "direction_label": heading_label(head["direction"] or "flat"),
                "rotation_score": None,  # filled in below, once the universe is known
                "date": head_date.strftime("%Y-%m-%d"),
                "relative_returns": {k: _rounded(v, 2) for k, v in returns.items()},
                "tail": [
                    {
                        "date": pd.Timestamp(stamp).strftime("%Y-%m-%d"),
                        "rs_ratio": _rounded(row["rs_ratio"]),
                        "rs_momentum": _rounded(row["rs_momentum"]),
                        "quadrant": row["quadrant"],
                    }
                    for stamp, row in tail.iterrows()
                ],
            }
        )

    if not sectors_payload:
        raise InsufficientHistory(
            "no sector produced a valid RRG point. "
            + (
                "; ".join(f"{u['symbol']}: {u['reason']}" for u in unavailable[:5])
                or "no sectors selected"
            )
        )

    settings = get_settings()
    weights = ScoreWeights(
        rs_ratio=settings.score_weight_rs_ratio,
        rs_momentum=settings.score_weight_rs_momentum,
        momentum_change=settings.score_weight_momentum_change,
    )
    scores = rotation_scores(latest_components, weights)
    for entry in sectors_payload:
        entry["rotation_score"] = scores.get(entry["symbol"])

    # Staleness. Sectors are plotted at their own most recent valid observation, which is
    # not always the chart's headline date: real feeds have gaps, and a sector whose data
    # stopped weeks ago would otherwise sit on the chart looking perfectly current. Rather
    # than hide the sector or silently carry its last value forward, each point states how
    # far behind it is and the UI marks it.
    bar_positions = {
        pd.Timestamp(stamp).strftime("%Y-%m-%d"): position
        for position, stamp in enumerate(benchmark_series.index)
    }
    headline_position = bar_positions.get(
        as_of_effective.strftime("%Y-%m-%d") if as_of_effective is not None else "", 0
    )
    for entry in sectors_payload:
        position = bar_positions.get(entry["date"])
        behind = None if position is None else headline_position - position
        entry["bars_behind"] = behind
        entry["is_stale"] = bool(behind is not None and behind > 0)

    rotations = [
        event.to_dict()
        for symbol, frame in frames.items()
        for event in detect_rotations(frame.tail(request.tail_length + 1), symbol)
    ]

    payload = {
        "benchmark": benchmark_row.symbol,
        "benchmark_name": benchmark_row.display_name,
        "frequency": request.frequency,
        "date": as_of_effective.strftime("%Y-%m-%d") if as_of_effective is not None else None,
        "requested_as_of": request.as_of.isoformat() if request.as_of else None,
        "tail_length": request.tail_length,
        "center": params.center,
        "engine_version": ENGINE_VERSION,
        "params": params.to_dict(),
        "params_fingerprint": params.fingerprint(),
        "warmup_bars": params.min_bars,
        "bars_available": len(benchmark_series),
        "sectors": sectors_payload,
        "unavailable": unavailable,
        "rotations": rotations,
        "score_note": (
            "Rotation score components are percentile ranks within the selected "
            "universe, so scores are not comparable across different sector selections."
        ),
    }

    if use_cache:
        cache.set(signature, payload)
    return payload


def available_dates(
    session: Session,
    benchmark: str,
    frequency: str,
    params: RRGParams | None = None,
    include_partial: bool = False,
) -> list[str]:
    """Dates the playback scrubber may land on (SRS 21).

    Only dates at or after the warm-up requirement are offered. Letting the user scrub
    into the warm-up window would show an empty chart with no explanation.
    """
    params = params or RRGParams()
    series = _series_for(session, benchmark, frequency, None, include_partial)
    if len(series) < params.min_bars:
        return []
    usable = series.index[params.min_bars - 1 :]
    return [pd.Timestamp(stamp).strftime("%Y-%m-%d") for stamp in usable]


def sector_detail(
    session: Session,
    symbol: str,
    request: RRGRequest,
) -> dict:
    """Full history plus statistics for one sector (SRS 18)."""
    from sqlalchemy import select

    sector = session.scalar(select(Sector).where(Sector.symbol == symbol))
    if sector is None:
        raise ValueError(f"unknown sector: {symbol}")

    benchmark_row = session.scalar(
        select(Benchmark).where(Benchmark.symbol == request.benchmark)
    )
    if benchmark_row is None:
        raise ValueError(f"unknown benchmark: {request.benchmark}")

    benchmark_series = _series_for(
        session, benchmark_row.symbol, request.frequency, request.as_of, request.include_partial
    )
    sector_series = _series_for(
        session,
        symbol,
        request.frequency,
        request.as_of,
        request.include_partial,
        weekly_grid=benchmark_series,
    )
    if sector_series.empty or benchmark_series.empty:
        raise InsufficientHistory(f"no stored data for {symbol} or {request.benchmark}")

    frame = compute_rrg(sector_series, benchmark_series, request.params)
    valid = frame.dropna(subset=["rs_ratio", "rs_momentum"])
    if valid.empty:
        raise InsufficientHistory(f"insufficient history for {symbol}")

    head = valid.iloc[-1]
    head_date = pd.Timestamp(valid.index[-1])
    returns = relative_returns(sector_series, benchmark_series, head_date, RETURN_WINDOWS)

    return {
        "symbol": sector.symbol,
        "name": sector.display_name,
        "full_name": sector.sector_name,
        "short_name": sector.short_name,
        "color": sector.color,
        "benchmark": benchmark_row.symbol,
        "frequency": request.frequency,
        "date": head_date.strftime("%Y-%m-%d"),
        "rs_ratio": _rounded(head["rs_ratio"]),
        "rs_momentum": _rounded(head["rs_momentum"]),
        "quadrant": head["quadrant"],
        "direction": head["direction"],
        "direction_label": heading_label(head["direction"] or "flat"),
        "relative_returns": {k: _rounded(v, 2) for k, v in returns.items()},
        "rotations": [e.to_dict() for e in detect_rotations(frame, symbol)][-25:],
        "history": [
            {
                "date": pd.Timestamp(stamp).strftime("%Y-%m-%d"),
                "rs": _rounded(row["rs"], 4),
                "rs_ratio": _rounded(row["rs_ratio"]),
                "rs_momentum": _rounded(row["rs_momentum"]),
                "quadrant": row["quadrant"],
            }
            for stamp, row in valid.iterrows()
        ],
    }


def persist_rotations(
    session: Session,
    benchmark: str,
    frequency: str,
    params: RRGParams | None = None,
    lookback_bars: int = 260,
) -> int:
    """Detect and store quadrant transitions for the default universe (SRS 23).

    Idempotent: the unique constraint on (date, sector, benchmark, timeframe, params)
    means re-running over an overlapping window inserts nothing new. Returns the number
    of newly stored events.
    """
    from sqlalchemy import select

    from ..models import RotationEventRow

    params = params or RRGParams()
    fingerprint = params.fingerprint()

    benchmark_row = session.scalar(select(Benchmark).where(Benchmark.symbol == benchmark))
    if benchmark_row is None:
        raise ValueError(f"unknown benchmark: {benchmark}")

    benchmark_series = _series_for(session, benchmark, frequency, None, False)
    if benchmark_series.empty:
        return 0

    sectors = list(
        session.scalars(
            select(Sector).where(Sector.active.is_(True)).order_by(Sector.sort_order)
        )
    )

    existing = {
        (row[0], row[1])
        for row in session.execute(
            select(RotationEventRow.date, RotationEventRow.sector_symbol).where(
                RotationEventRow.benchmark_symbol == benchmark,
                RotationEventRow.timeframe == frequency,
                RotationEventRow.params_fingerprint == fingerprint,
            )
        ).all()
    }

    inserted = 0
    for sector in sectors:
        sector_series = _series_for(
            session, sector.symbol, frequency, None, False, weekly_grid=benchmark_series
        )
        if sector_series.empty:
            continue
        try:
            frame = compute_rrg(sector_series, benchmark_series, params)
        except Exception:  # noqa: BLE001
            logger.exception("rotation scan failed for %s", sector.symbol)
            continue

        window = frame.dropna(subset=["quadrant"]).tail(lookback_bars)
        for event in detect_rotations(window, sector.symbol):
            event_date = pd.Timestamp(event.date).date()
            if (event_date, sector.symbol) in existing:
                continue
            session.add(
                RotationEventRow(
                    date=event_date,
                    sector_symbol=sector.symbol,
                    benchmark_symbol=benchmark,
                    timeframe=frequency,
                    params_fingerprint=fingerprint,
                    previous_quadrant=event.previous_quadrant,
                    current_quadrant=event.current_quadrant,
                    signal=event.signal,
                    rs_ratio=event.rs_ratio,
                    rs_momentum=event.rs_momentum,
                )
            )
            existing.add((event_date, sector.symbol))
            inserted += 1

    session.commit()
    logger.info(
        "stored %d new rotation events for %s/%s", inserted, benchmark, frequency
    )
    return inserted


def export_rows(session: Session, request: RRGRequest) -> list[dict]:
    """Flat rows for CSV/Excel export (SRS 41).

    Built from the same `build_rrg` payload the screen renders, so exported values match
    what the user is looking at (SRS 52.8) by construction rather than by coincidence.
    """
    payload = build_rrg(session, request)
    rows: list[dict] = []
    for sector in payload["sectors"]:
        returns = sector["relative_returns"]
        for point in sector["tail"]:
            is_head = point["date"] == sector["date"]
            rows.append(
                {
                    "date": point["date"],
                    "sector": sector["name"],
                    "symbol": sector["symbol"],
                    "benchmark": payload["benchmark"],
                    "frequency": payload["frequency"],
                    "rs_ratio": point["rs_ratio"],
                    "rs_momentum": point["rs_momentum"],
                    "quadrant": point["quadrant"],
                    "is_latest": is_head,
                    # Point-in-time statistics belong to the head of the tail only;
                    # repeating them on every row would imply they were recomputed
                    # historically, which they were not.
                    "rotation_score": sector["rotation_score"] if is_head else None,
                    "direction": sector["direction"] if is_head else None,
                    "rel_return_1d": returns.get("1d") if is_head else None,
                    "rel_return_1w": returns.get("1w") if is_head else None,
                    "rel_return_1m": returns.get("1m") if is_head else None,
                    "rel_return_3m": returns.get("3m") if is_head else None,
                    "rel_return_6m": returns.get("6m") if is_head else None,
                    "rel_return_1y": returns.get("1y") if is_head else None,
                    "engine_version": payload["engine_version"],
                    "params_fingerprint": payload["params_fingerprint"],
                }
            )
    rows.sort(key=lambda r: (r["sector"], r["date"]))
    return rows
