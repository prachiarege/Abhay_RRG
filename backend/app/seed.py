"""Sector and benchmark universe seeding (SRS 2.1, 2.2, 52).

The universe lives in the database, never in application logic -- SRS 2.1 is explicit
that the sector list must not be hard-coded. This module only provides the INITIAL rows;
after seeding, the universe is edited through the admin API or directly in the table.

Every provider symbol below was verified against the live Yahoo feed on 2026-08-19.
Three sectors from SRS 2.1 have no usable Yahoo series and are seeded inactive with the
reason recorded, so the gap is visible in the admin UI rather than presenting as a silent
"no data" on the chart:

    NIFTY Oil & Gas          - no Yahoo symbol resolves
    NIFTY Consumer Durables  - no Yahoo symbol resolves
    NIFTY Healthcare         - no Yahoo symbol resolves

They activate as soon as a provider that carries them is configured (a licensed NSE feed
does), which needs a provider_symbol edit and nothing else.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Benchmark, Sector

logger = logging.getLogger(__name__)

# (symbol, name, display, short, provider_symbol, is_default, active, order, colour)
#
# `is_default` marks the curated on-screen universe. The full SRS 2.1 list is heavily
# collinear -- Bank / Financial Services / PSU Bank / Private Bank track each other
# closely, as do Metal / Energy / Commodities / Infrastructure -- and plotting all of
# them at once produces an unreadable cluster of near-identical points. The overlapping
# indices remain available and one click away; they just start unchecked.
SECTORS: tuple[tuple, ...] = (
    ("NIFTY_AUTO",        "NIFTY Auto",               "Auto",         "AUTO",   "^CNXAUTO",             True,  True,  10, "#22c55e"),
    ("NIFTY_BANK",        "NIFTY Bank",               "Bank",         "BANK",   "^NSEBANK",             True,  True,  20, "#3b82f6"),
    ("NIFTY_FMCG",        "NIFTY FMCG",               "FMCG",         "FMCG",   "^CNXFMCG",             True,  True,  30, "#eab308"),
    ("NIFTY_IT",          "NIFTY IT",                 "IT",           "IT",     "^CNXIT",               True,  True,  40, "#06b6d4"),
    ("NIFTY_PHARMA",      "NIFTY Pharma",             "Pharma",       "PHARMA", "^CNXPHARMA",           True,  True,  50, "#a855f7"),
    ("NIFTY_METAL",       "NIFTY Metal",              "Metal",        "METAL",  "^CNXMETAL",            True,  True,  60, "#f97316"),
    ("NIFTY_REALTY",      "NIFTY Realty",             "Realty",       "REALTY", "^CNXREALTY",           True,  True,  70, "#ec4899"),
    ("NIFTY_MEDIA",       "NIFTY Media",              "Media",        "MEDIA",  "^CNXMEDIA",            True,  True,  80, "#f43f5e"),
    ("NIFTY_ENERGY",      "NIFTY Energy",             "Energy",       "ENERGY", "^CNXENERGY",           True,  True,  90, "#84cc16"),
    ("NIFTY_INFRA",       "NIFTY Infrastructure",     "Infra",        "INFRA",  "^CNXINFRA",            True,  True, 100, "#14b8a6"),
    # Available but off by default -- overlap heavily with the curated set above.
    ("NIFTY_FINSERV",     "NIFTY Financial Services", "Fin Services", "FINSRV", "NIFTY_FIN_SERVICE.NS", False, True, 110, "#60a5fa"),
    ("NIFTY_PSU_BANK",    "NIFTY PSU Bank",           "PSU Bank",     "PSUBNK", "^CNXPSUBANK",          False, True, 120, "#818cf8"),
    ("NIFTY_PVT_BANK",    "NIFTY Private Bank",       "Private Bank", "PVTBNK", "NIFTY_PVT_BANK.NS",    False, True, 130, "#38bdf8"),
    ("NIFTY_COMMODITIES", "NIFTY Commodities",        "Commodities",  "COMDTY", "^CNXCMDT",             False, True, 140, "#fb923c"),
    # In SRS 2.1 but unavailable from the default provider. Seeded inactive on purpose.
    ("NIFTY_OIL_GAS",     "NIFTY Oil & Gas",          "Oil & Gas",    "OILGAS", "UNAVAILABLE_OILGAS",   False, False, 150, "#fbbf24"),
    ("NIFTY_CONSUMER_DUR","NIFTY Consumer Durables",  "Cons Durables","CONDUR", "UNAVAILABLE_CONSDUR",  False, False, 160, "#c084fc"),
    ("NIFTY_HEALTHCARE",  "NIFTY Healthcare",         "Healthcare",   "HEALTH", "UNAVAILABLE_HEALTH",   False, False, 170, "#4ade80"),
)

# (symbol, name, display, provider_symbol, is_default, active, order)
BENCHMARKS: tuple[tuple, ...] = (
    ("NIFTY500",     "NIFTY 500",       "NIFTY 500",       "^CRSLDX",    True,  True,  10),
    ("NIFTY50",      "NIFTY 50",        "NIFTY 50",        "^NSEI",      False, True,  20),
    ("NIFTY100",     "NIFTY 100",       "NIFTY 100",       "^CNX100",    False, True,  30),
    ("NIFTYMIDCAP50","NIFTY Midcap 50", "NIFTY Midcap 50", "^NSEMDCP50", False, True,  40),
    # SRS 2.2 asks for Midcap 150 and Smallcap 250; neither resolves on Yahoo. Seeded
    # inactive so the intent is recorded and a licensed feed can switch them on.
    ("NIFTYMIDCAP150", "NIFTY Midcap 150",   "NIFTY Midcap 150",   "UNAVAILABLE_MID150",   False, False, 50),
    ("NIFTYSMLCAP250", "NIFTY Smallcap 250", "NIFTY Smallcap 250", "UNAVAILABLE_SMALL250", False, False, 60),
)

UNAVAILABLE_PREFIX = "UNAVAILABLE_"


def seed_universe(session: Session, overwrite: bool = False) -> dict[str, int]:
    """Insert the initial universe. Idempotent.

    Args:
        session: open session; the caller commits.
        overwrite: refresh provider symbols and display metadata on existing rows.
            Never touches `active` or `is_default`, so an operator's own choices in the
            admin panel survive a re-seed.
    """
    created = {"sectors": 0, "benchmarks": 0, "updated": 0}

    for (symbol, name, display, short, provider_symbol, is_default, active, order, colour) in SECTORS:
        existing = session.scalar(select(Sector).where(Sector.symbol == symbol))
        if existing is None:
            session.add(
                Sector(
                    symbol=symbol,
                    sector_name=name,
                    display_name=display,
                    short_name=short,
                    provider_symbol=provider_symbol,
                    exchange="NSE",
                    benchmark_group="NSE_SECTORAL",
                    is_default=is_default,
                    active=active,
                    sort_order=order,
                    color=colour,
                )
            )
            created["sectors"] += 1
        elif overwrite:
            existing.sector_name = name
            existing.display_name = display
            existing.short_name = short
            existing.provider_symbol = provider_symbol
            existing.sort_order = order
            existing.color = colour
            created["updated"] += 1

    for (symbol, name, display, provider_symbol, is_default, active, order) in BENCHMARKS:
        existing = session.scalar(select(Benchmark).where(Benchmark.symbol == symbol))
        if existing is None:
            session.add(
                Benchmark(
                    symbol=symbol,
                    benchmark_name=name,
                    display_name=display,
                    provider_symbol=provider_symbol,
                    exchange="NSE",
                    is_default=is_default,
                    active=active,
                    sort_order=order,
                )
            )
            created["benchmarks"] += 1
        elif overwrite:
            existing.benchmark_name = name
            existing.display_name = display
            existing.provider_symbol = provider_symbol
            existing.sort_order = order
            created["updated"] += 1

    logger.info("universe seeded: %s", created)
    return created


def ingestable_symbols(session: Session) -> dict[str, str]:
    """{canonical symbol: provider symbol} for every active row worth fetching.

    Placeholder provider symbols are filtered out so a refresh does not waste requests
    on indices the configured provider is known not to carry.
    """
    out: dict[str, str] = {}
    for sector in session.scalars(select(Sector).where(Sector.active.is_(True))):
        if not sector.provider_symbol.startswith(UNAVAILABLE_PREFIX):
            out[sector.symbol] = sector.provider_symbol
    for benchmark in session.scalars(select(Benchmark).where(Benchmark.active.is_(True))):
        if not benchmark.provider_symbol.startswith(UNAVAILABLE_PREFIX):
            out[benchmark.symbol] = benchmark.provider_symbol
    return out
