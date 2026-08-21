"""Data ingestion (SRS 5, 29, 45, 46).

Failure isolation is the governing principle: one unavailable sector must never stop the
others (SRS 46). Every symbol is fetched, validated and stored independently, and the
run is summarised into `ingestion_log` whether it fully succeeded or not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import Benchmark, IngestionLog, PriceData, Sector
from ..providers import DataProvider, get_provider
from ..providers.base import OHLCFrame
from ..seed import ingestable_symbols
from .validation import ValidationReport, validate_price_series

logger = logging.getLogger(__name__)

UPSERT_COLUMNS = ("open", "high", "low", "close", "adjusted_close", "volume", "ingested_at")


@dataclass
class IngestionResult:
    provider: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    requested: list[str] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    rows_written: int = 0
    reports: dict[str, ValidationReport] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.succeeded:
            return "failed"
        return "partial" if self.failed else "success"

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "trigger": self.trigger,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "requested": len(self.requested),
            "succeeded": len(self.succeeded),
            "failed": self.failed,
            "rows_written": self.rows_written,
            "validation": {k: v.to_dict() for k, v in self.reports.items()},
        }


def _upsert(session: Session, rows: list[dict]) -> int:
    """Insert-or-update price rows, portably.

    SQLite and Postgres both support ON CONFLICT, so the only dialect-specific part is
    which `insert` construct to build. Anything else falls back to a read-then-write
    path rather than failing.
    """
    if not rows:
        return 0

    dialect = session.get_bind().dialect.name
    if dialect in ("sqlite", "postgresql"):
        builder = sqlite_insert if dialect == "sqlite" else pg_insert
        statement = builder(PriceData).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["symbol", "date", "source"],
            set_={column: getattr(statement.excluded, column) for column in UPSERT_COLUMNS},
        )
        session.execute(statement)
        return len(rows)

    # Generic fallback: skip rows that already exist, insert the rest.
    keys = {(r["symbol"], r["date"], r["source"]) for r in rows}
    existing = set(
        session.execute(
            select(PriceData.symbol, PriceData.date, PriceData.source).where(
                PriceData.symbol.in_({k[0] for k in keys})
            )
        ).all()
    )
    fresh = [r for r in rows if (r["symbol"], r["date"], r["source"]) not in existing]
    if fresh:
        session.bulk_insert_mappings(PriceData, fresh)
    return len(fresh)


def _frame_to_rows(symbol: str, payload: OHLCFrame) -> list[dict]:
    now = datetime.now(timezone.utc)
    frame = payload.frame
    rows: list[dict] = []
    for stamp, row in frame.iterrows():
        close = row.get("close")
        if pd.isna(close):
            continue
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp(stamp).date(),
                "source": payload.source,
                "open": None if pd.isna(row.get("open")) else float(row["open"]),
                "high": None if pd.isna(row.get("high")) else float(row["high"]),
                "low": None if pd.isna(row.get("low")) else float(row["low"]),
                "close": float(close),
                "adjusted_close": None,
                "volume": None if pd.isna(row.get("volume")) else float(row["volume"]),
                "ingested_at": now,
            }
        )
    return rows


def refresh_prices(
    session: Session,
    provider: DataProvider | None = None,
    symbols: dict[str, str] | None = None,
    start: date | None = None,
    end: date | None = None,
    trigger: str = "manual",
) -> IngestionResult:
    """Fetch, validate and store price history for the active universe.

    Args:
        session: open session; this function commits its own work.
        provider: override the configured provider.
        symbols: {canonical: provider_symbol}; defaults to the whole active universe.
        start: earliest date to request. None means the provider's full window.
        trigger: "manual" | "scheduled" | "startup", recorded in the audit log.
    """
    provider = provider or get_provider()
    # Resolve identifiers for THIS provider, not the configured default. Passing
    # provider=nse while resolving Yahoo tickers would send "^CNXIT" to the NSE archive,
    # which would then look for an index literally named that.
    symbols = (
        symbols if symbols is not None
        else ingestable_symbols(session, provider=provider.name)
    )

    result = IngestionResult(
        provider=provider.name,
        trigger=trigger,
        started_at=datetime.now(timezone.utc),
        requested=sorted(symbols),
    )

    log_row = IngestionLog(
        started_at=result.started_at,
        provider=provider.name,
        trigger=trigger,
        symbols_requested=len(symbols),
        status="running",
    )
    session.add(log_row)
    session.commit()

    fetched, errors = provider.fetch_many(symbols, start=start, end=end)
    result.failed.update(errors)
    for symbol, message in errors.items():
        logger.error("ingestion failed for %s: %s", symbol, message)

    # A partial-window backfill legitimately returns fewer bars than a full refresh, so gap
    # detection against the benchmark calendar is only meaningful for a full-history run.
    partial_window = start is not None

    # Gap detection needs a reference calendar, and the benchmark is the authority on which
    # days were sessions (SRS 28). Without this, a sector missing a month of data validates
    # perfectly cleanly -- which is how such a gap reaches the chart unnoticed.
    from ..config import get_settings

    default_benchmark = get_settings().default_benchmark
    reference_calendar = None
    benchmark_payload = fetched.get(default_benchmark)
    if benchmark_payload is not None:
        reference_calendar = benchmark_payload.frame.index

    for symbol, payload in fetched.items():
        report = validate_price_series(
            payload.close,
            symbol,
            expected_calendar=(
                None
                if (partial_window or symbol == default_benchmark)
                else reference_calendar
            ),
        )
        report.log()
        result.reports[symbol] = report

        if not report.ok:
            result.failed[symbol] = (
                f"validation failed: duplicates={len(report.duplicate_dates)} "
                f"non_positive={len(report.non_positive_values)}"
            )
            continue

        rows = _frame_to_rows(symbol, payload)
        try:
            written = _upsert(session, rows)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("failed storing %s", symbol)
            result.failed[symbol] = f"storage error: {exc}"
            continue

        result.rows_written += written
        result.succeeded.append(symbol)

    result.finished_at = datetime.now(timezone.utc)
    log_row.finished_at = result.finished_at
    log_row.symbols_succeeded = len(result.succeeded)
    log_row.rows_written = result.rows_written
    log_row.status = result.status
    log_row.detail = (
        "; ".join(f"{k}: {v}" for k, v in sorted(result.failed.items())) or None
    )
    session.commit()

    logger.info(
        "ingestion %s: %d/%d symbols, %d rows",
        result.status,
        len(result.succeeded),
        len(result.requested),
        result.rows_written,
    )
    return result


def _price_query(symbol: str, source: str | None) -> Select:
    query = select(PriceData.date, PriceData.close).where(PriceData.symbol == symbol)
    if source is not None:
        query = query.where(PriceData.source == source)
    return query.order_by(PriceData.date)


def _rows_by_source(session: Session, symbol: str) -> dict[str, list[tuple]]:
    """All stored bars for a symbol, grouped by which provider supplied them."""
    grouped: dict[str, list[tuple]] = {}
    for source, day, close in session.execute(
        select(PriceData.source, PriceData.date, PriceData.close)
        .where(PriceData.symbol == symbol)
        .order_by(PriceData.date)
    ).all():
        grouped.setdefault(source, []).append((day, close))
    return grouped


def source_breakdown(
    session: Session,
    symbol: str,
    priority: list[str] | None = None,
) -> dict[str, int]:
    """How many bars each source actually CONTRIBUTES to the merged series.

    Not simply a row count per source: a lower-priority source contributes only the dates
    no higher-priority source covers. This is what makes the merge auditable rather than
    silent -- SRS V2 6.4 forbids a series quietly alternating between providers, and the
    honest way to satisfy that is to say exactly who supplied what.
    """
    if priority is None:
        from ..config import get_settings

        priority = get_settings().source_priority_list

    grouped = _rows_by_source(session, symbol)
    ordered = [s for s in priority if s in grouped] + [
        s for s in sorted(grouped) if s not in priority
    ]

    claimed: set = set()
    contribution: dict[str, int] = {}
    for source in ordered:
        dates = {day for day, close in grouped[source] if close is not None}
        fresh = dates - claimed
        if fresh:
            contribution[source] = len(fresh)
            claimed |= fresh
    return contribution


def load_close_series(
    session: Session,
    symbol: str,
    source: str | None = None,
    end: date | None = None,
    priority: list[str] | None = None,
) -> pd.Series:
    """Daily close series for one symbol, ascending, as a float Series.

    When several providers have supplied the same symbol, sources are merged in priority
    order: a date present in a higher-priority source wins, and lower-priority sources fill
    only the dates it lacks. Pass `source` to pin the series to one provider exactly.

    Why merge rather than pick one: the deep history and the current tail can legitimately
    come from different places. Yahoo holds twelve years but stopped publishing several
    sector indices for a month; NSE's archive has those missing days but would take
    thousands of day-file requests to reproduce twelve years. Refusing to merge would mean
    choosing between a long series with a hole and a short series without one -- and a hole
    is worse than a join, because a NaN inside a rolling window suppresses months of output.

    The merge is explicit, not silent: `source_breakdown` reports exactly which provider
    supplied how many bars, and the API surfaces it.
    """
    if source is not None:
        rows = session.execute(_price_query(symbol, source)).all()
        if not rows:
            return pd.Series(dtype="float64", index=pd.DatetimeIndex([], name="date"))
        index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows], name="date")
        series = pd.Series([float(r[1]) for r in rows], index=index, name=symbol)
    else:
        if priority is None:
            from ..config import get_settings

            priority = get_settings().source_priority_list

        grouped = _rows_by_source(session, symbol)
        if not grouped:
            return pd.Series(dtype="float64", index=pd.DatetimeIndex([], name="date"))

        # Unlisted sources still get used, after the listed ones, so a provider added
        # without a config update contributes rather than being silently ignored.
        ordered = [s for s in priority if s in grouped] + [
            s for s in sorted(grouped) if s not in priority
        ]

        merged: pd.Series | None = None
        for source_name in ordered:
            rows = grouped[source_name]
            index = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows], name="date")
            part = pd.Series(
                [float(c) for _, c in rows], index=index, name=symbol, dtype="float64"
            )
            part = part[~part.index.duplicated(keep="last")].sort_index()
            merged = part if merged is None else merged.combine_first(part)
        series = merged if merged is not None else pd.Series(
            dtype="float64", index=pd.DatetimeIndex([], name="date")
        )

    series = series[~series.index.duplicated(keep="last")].sort_index()
    if end is not None:
        series = series[series.index <= pd.Timestamp(end)]
    return series


def provider_usage(session: Session) -> dict:
    """Which providers are actually supplying stored data, universe-wide.

    SRS V2 6.4 requires the UI to indicate the provider actually serving the data, and
    forbids a series silently alternating between providers. One grouped query gives the
    whole picture cheaply; `source_breakdown` gives the exact per-symbol contribution when
    a user drills in.
    """
    from sqlalchemy import func

    rows = session.execute(
        select(PriceData.source, func.count(PriceData.symbol.distinct()), func.count(),
               func.max(PriceData.date))
        .group_by(PriceData.source)
    ).all()
    return {
        source: {
            "symbols": int(symbols),
            "rows": int(total),
            "latest_date": latest.isoformat() if latest else None,
        }
        for source, symbols, total, latest in rows
    }


def data_freshness(session: Session) -> dict:
    """Latest stored observation per symbol, for the header and health endpoints."""
    from sqlalchemy import func

    rows = session.execute(
        select(PriceData.symbol, func.max(PriceData.date)).group_by(PriceData.symbol)
    ).all()
    latest = {symbol: stamp for symbol, stamp in rows if stamp is not None}
    overall = max(latest.values()) if latest else None
    return {
        "symbols": len(latest),
        "latest_date": overall.isoformat() if overall else None,
        "per_symbol": {k: v.isoformat() for k, v in sorted(latest.items())},
    }


def last_ingestion(session: Session) -> dict | None:
    row = session.scalar(select(IngestionLog).order_by(IngestionLog.id.desc()).limit(1))
    if row is None:
        return None
    return {
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "provider": row.provider,
        "trigger": row.trigger,
        "status": row.status,
        "symbols_requested": row.symbols_requested,
        "symbols_succeeded": row.symbols_succeeded,
        "rows_written": row.rows_written,
        "detail": row.detail,
    }


def refresh_sector_stocks(
    session: Session,
    sector_symbol: str,
    provider: DataProvider | None = None,
    start: date | None = None,
    only_missing: bool = True,
    trigger: str = "drilldown",
) -> IngestionResult:
    """Fetch price history for one sector's constituents.

    Called lazily the first time a user drills into a sector, rather than downloading every
    constituent of every sector up front. There are roughly 180 memberships across the
    universe; fetching them all would turn the desktop app's two-minute first run into
    something closer to ten, to load data for sectors the user may never open.

    A stock the provider cannot serve is marked `data_available = False`, so subsequent
    refreshes skip it instead of retrying a symbol that does not exist.

    Args:
        only_missing: skip stocks that already have stored prices. Set False to force a
            re-fetch of the whole sector.
    """
    from ..models import Stock

    provider = provider or get_provider()

    if start is None:
        # Stock-level RRG does not need the full index history: a 60-period weekly tail plus
        # warm-up spans roughly two years. Eight is generous and keeps each fetch smaller.
        start = date.today() - timedelta(days=int(8 * 365.25))

    members = list(
        session.scalars(
            select(Stock)
            .where(Stock.sector_symbol == sector_symbol, Stock.active.is_(True))
            .order_by(Stock.sort_order)
        )
    )
    if not members:
        raise ValueError(f"no constituents recorded for {sector_symbol}")

    if only_missing:
        existing = {
            row[0]
            for row in session.execute(
                select(PriceData.symbol).where(
                    PriceData.symbol.in_([m.symbol for m in members])
                ).distinct()
            ).all()
        }
        pending = [m for m in members if m.symbol not in existing and m.data_available]
    else:
        pending = [m for m in members if m.data_available]

    result = IngestionResult(
        provider=provider.name,
        trigger=trigger,
        started_at=datetime.now(timezone.utc),
        requested=[m.symbol for m in pending],
    )

    if not pending:
        result.finished_at = datetime.now(timezone.utc)
        return result

    logger.info(
        "fetching %d constituents of %s from %s",
        len(pending),
        sector_symbol,
        provider.name,
    )

    fetched, errors = provider.fetch_many(
        {m.symbol: m.provider_symbol for m in pending}, start=start
    )
    result.failed.update(errors)

    by_symbol = {m.symbol: m for m in pending}
    for symbol, message in errors.items():
        logger.warning("no data for %s: %s", symbol, message)
        row = by_symbol.get(symbol)
        if row is not None:
            # Remember the failure so the next refresh does not retry a dead symbol.
            row.data_available = False

    for symbol, payload in fetched.items():
        report = validate_price_series(payload.close, symbol)
        result.reports[symbol] = report
        if not report.ok:
            result.failed[symbol] = "validation failed"
            continue
        try:
            result.rows_written += _upsert(session, _frame_to_rows(symbol, payload))
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("failed storing %s", symbol)
            result.failed[symbol] = f"storage error: {exc}"
            continue
        result.succeeded.append(symbol)

    session.commit()
    result.finished_at = datetime.now(timezone.utc)
    logger.info(
        "constituents of %s: %d/%d fetched, %d rows",
        sector_symbol,
        len(result.succeeded),
        len(result.requested),
        result.rows_written,
    )
    return result


def universe(session: Session) -> tuple[list[Sector], list[Benchmark]]:
    sectors = list(
        session.scalars(
            select(Sector).where(Sector.active.is_(True)).order_by(Sector.sort_order)
        )
    )
    benchmarks = list(
        session.scalars(
            select(Benchmark)
            .where(Benchmark.active.is_(True))
            .order_by(Benchmark.sort_order)
        )
    )
    return sectors, benchmarks
