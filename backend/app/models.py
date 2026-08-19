"""SQLAlchemy models (SRS 32), with three corrections to the suggested schema.

1.  ``price_data`` gets a real composite primary key ``(symbol, date, source)``. The
    SRS requires duplicate-date detection (27); a uniqueness constraint provides it
    at the storage layer instead of hoping application code remembers.
2.  ``price_data`` gets a ``source`` column. SRS 5.4 mandates multiple providers but
    the suggested schema had nowhere to record which one supplied a row, making
    provider disagreements undebuggable.
3.  ``rrg_values`` gets ``params_fingerprint`` and ``engine_version`` in its primary
    key. The SRS exposes rs_period/momentum_period/smoothing as user controls (13.1)
    while also requiring precomputation (37) and versioned calculations (50.3) --
    without these columns, precomputed rows from different parameter sets are
    indistinguishable from one another.

Written to be Postgres-compatible: no SQLite-only types, explicit lengths on strings.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timestamps are stored in UTC and rendered in IST at the edge (SRS 29)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Sector(Base):
    __tablename__ = "sectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", nullable=False)
    benchmark_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    short_name: Mapped[str] = mapped_column(String(24), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Curated sectors form the default on-screen universe. The rest stay available but
    # unchecked, because the full SRS 2.1 list is heavily collinear (Bank / Financial
    # Services / PSU Bank / Private Bank overlap enough to clutter the plot).
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Sector {self.symbol}>"


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Stock(Base):
    """An index constituent — one row per (sector, stock) membership.

    A company belonging to several indices gets several rows: HDFCBANK is in NIFTY Bank,
    NIFTY Financial Services and NIFTY Private Bank. Membership is the fact recorded here,
    not the company, which keeps "which stocks are in this sector" a single indexed lookup.

    `as_of` dates the membership snapshot. See app/constituents.py for why that matters:
    index composition changes, so a stock-level historical view built from a current
    snapshot carries composition bias and the UI must be able to say which snapshot it used.
    """

    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector_symbol: Mapped[str] = mapped_column(
        String(64), ForeignKey("sectors.symbol"), nullable=False
    )
    provider_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Set false once a provider has been asked for this symbol and had nothing, so repeat
    # refreshes stop wasting requests on it.
    data_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("sector_symbol", "symbol", name="uq_stock_membership"),
        Index("ix_stock_sector", "sector_symbol"),
        Index("ix_stock_symbol", "symbol"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Stock {self.symbol} in {self.sector_symbol}>"


class PriceData(Base):
    __tablename__ = "price_data"

    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    # Meaningless for an index, retained for when the universe extends to securities.
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_price_symbol_date", "symbol", "date"),
        Index("ix_price_date", "date"),
    )


class RRGValue(Base):
    """Precomputed RRG points. Cache, not source of truth -- safe to drop and rebuild."""

    __tablename__ = "rrg_values"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    sector_symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    benchmark_symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(16), primary_key=True)
    params_fingerprint: Mapped[str] = mapped_column(String(32), primary_key=True)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    rs: Mapped[float | None] = mapped_column(Float, nullable=True)
    rs_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    rs_momentum: Mapped[float | None] = mapped_column(Float, nullable=True)
    quadrant: Mapped[str | None] = mapped_column(String(16), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rotation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index(
            "ix_rrg_lookup",
            "benchmark_symbol",
            "timeframe",
            "params_fingerprint",
            "date",
        ),
    )


class RotationEventRow(Base):
    __tablename__ = "rotation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    sector_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    benchmark_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    params_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_quadrant: Mapped[str] = mapped_column(String(16), nullable=False)
    current_quadrant: Mapped[str] = mapped_column(String(16), nullable=False)
    signal: Mapped[str] = mapped_column(String(32), nullable=False)
    rs_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    rs_momentum: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "date",
            "sector_symbol",
            "benchmark_symbol",
            "timeframe",
            "params_fingerprint",
            name="uq_rotation_event",
        ),
        Index("ix_rotation_date", "date"),
    )


class IngestionLog(Base):
    """Audit trail for data refreshes (SRS 45)."""

    __tablename__ = "ingestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    symbols_requested: Mapped[int] = mapped_column(Integer, default=0)
    symbols_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppConfig(Base):
    """Admin-editable key/value overrides (SRS 40)."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
