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
    # Yahoo carries none of these three, but the NSE archive does -- verified against a
    # live file. They are active now, with no Yahoo entry in `provider_symbols`, so a
    # Yahoo-only refresh skips them while an NSE refresh picks them up.
    ("NIFTY_OIL_GAS",     "NIFTY Oil & Gas",          "Oil & Gas",    "OILGAS", "UNAVAILABLE_OILGAS",   False, True,  150, "#fbbf24"),
    ("NIFTY_CONSUMER_DUR","NIFTY Consumer Durables",  "Cons Durables","CONDUR", "UNAVAILABLE_CONSDUR",  False, True,  160, "#c084fc"),
    ("NIFTY_HEALTHCARE",  "NIFTY Healthcare",         "Healthcare",   "HEALTH", "UNAVAILABLE_HEALTH",   False, True,  170, "#4ade80"),
)

# (symbol, name, display, provider_symbol, is_default, active, order)
BENCHMARKS: tuple[tuple, ...] = (
    ("NIFTY500",     "NIFTY 500",       "NIFTY 500",       "^CRSLDX",    True,  True,  10),
    ("NIFTY50",      "NIFTY 50",        "NIFTY 50",        "^NSEI",      False, True,  20),
    ("NIFTY100",     "NIFTY 100",       "NIFTY 100",       "^CNX100",    False, True,  30),
    ("NIFTYMIDCAP50","NIFTY Midcap 50", "NIFTY Midcap 50", "^NSEMDCP50", False, True,  40),
    # SRS 2.2 asks for these two; neither resolves on Yahoo, but both are in the NSE
    # archive, so they are active with an NSE-only mapping.
    ("NIFTYMIDCAP150", "NIFTY Midcap 150",   "NIFTY Midcap 150",   "UNAVAILABLE_MID150",   False, True,  50),
    ("NIFTYSMLCAP250", "NIFTY Smallcap 250", "NIFTY Smallcap 250", "UNAVAILABLE_SMALL250", False, True,  60),
)

UNAVAILABLE_PREFIX = "UNAVAILABLE_"

#: Providers whose identifiers come from their own namespace, where guessing is wrong.
#: NSE keys on its own index names ("Nifty IT"), Dhan on numeric security ids -- handing
#: either a Yahoo ticker would make them search for an index literally called "^CNXIT".
#:
#: Everything else accepts the generic symbol: Yahoo because the legacy column always held
#: a Yahoo ticker, and CSV because it keys on a filename the operator chooses. Those may
#: fall back to `provider_symbol` when the map has no explicit entry.
NAMESPACED_PROVIDERS = frozenset({"nse", "dhan"})

#: NSE's own spelling of each index in ind_close_all_DDMMYYYY.csv, verified against a live
#: archive file. These become the `nse` entries in `provider_symbols`.
#:
#: Note what this unlocks: NSE publishes ~161 indices against Yahoo's 14, so the three
#: sectors SRS 2.1 asked for that Yahoo never carried (Oil & Gas, Consumer Durables,
#: Healthcare) become reachable, as do the Midcap 150 and Smallcap 250 benchmarks.
NSE_INDEX_NAMES: dict[str, str] = {
    # sectors
    "NIFTY_AUTO": "Nifty Auto",
    "NIFTY_BANK": "Nifty Bank",
    "NIFTY_FMCG": "Nifty FMCG",
    "NIFTY_IT": "Nifty IT",
    "NIFTY_PHARMA": "Nifty Pharma",
    "NIFTY_METAL": "Nifty Metal",
    "NIFTY_REALTY": "Nifty Realty",
    "NIFTY_MEDIA": "Nifty Media",
    "NIFTY_ENERGY": "Nifty Energy",
    "NIFTY_INFRA": "Nifty Infrastructure",
    "NIFTY_FINSERV": "Nifty Financial Services",
    "NIFTY_PSU_BANK": "Nifty PSU Bank",
    "NIFTY_PVT_BANK": "Nifty Private Bank",
    "NIFTY_COMMODITIES": "Nifty Commodities",
    "NIFTY_OIL_GAS": "Nifty Oil & Gas",
    "NIFTY_CONSUMER_DUR": "Nifty Consumer Durables",
    "NIFTY_HEALTHCARE": "Nifty Healthcare Index",
    # benchmarks
    "NIFTY500": "Nifty 500",
    "NIFTY50": "Nifty 50",
    "NIFTY100": "Nifty 100",
    "NIFTYMIDCAP50": "Nifty Midcap 50",
    "NIFTYMIDCAP150": "Nifty Midcap 150",
    "NIFTYSMLCAP250": "Nifty Smallcap 250",
}


def provider_symbol_map(symbol: str, yahoo_symbol: str) -> dict:
    """Build the per-provider identifier map for one index (V2-DATA-001).

    A placeholder Yahoo symbol is omitted rather than stored, so an absent key means
    "this provider has no identifier for this index" instead of "the identifier is a
    magic string the caller must remember to check".
    """
    mapping: dict[str, object] = {}
    if not yahoo_symbol.startswith(UNAVAILABLE_PREFIX):
        mapping["yahoo"] = yahoo_symbol
    nse_name = NSE_INDEX_NAMES.get(symbol)
    if nse_name:
        mapping["nse"] = nse_name
    return mapping


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

        if existing is not None and existing.provider_symbols is None:
            # Upgrade path. `overwrite` deliberately never touches operator-controlled
            # fields, but a row that predates per-provider mapping has NEVER had these set,
            # so filling them in is completing an install rather than overriding a choice.
            # Without this an existing database gets the new column and no data, and every
            # provider that needs an explicit mapping resolves zero symbols.
            existing.provider_symbols = provider_symbol_map(symbol, provider_symbol)
            existing.index_type = existing.index_type or "sector"
            if active and not existing.active:
                # This row was inactive because the old single provider could not serve it,
                # not because anyone chose to disable it. A configured provider can now.
                existing.active = True
                logger.info(
                    "activating %s: a configured provider now serves it", symbol
                )
            created["updated"] += 1

        if existing is None:
            session.add(
                Sector(
                    symbol=symbol,
                    sector_name=name,
                    display_name=display,
                    short_name=short,
                    provider_symbol=provider_symbol,
                    provider_symbols=provider_symbol_map(symbol, provider_symbol),
                    exchange="NSE",
                    index_type="sector",
                    benchmark_allowed=False,
                    sector_analysis_allowed=True,
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
            existing.provider_symbols = provider_symbol_map(symbol, provider_symbol)
            existing.index_type = existing.index_type or "sector"
            existing.sort_order = order
            existing.color = colour
            created["updated"] += 1

    for (symbol, name, display, provider_symbol, is_default, active, order) in BENCHMARKS:
        existing = session.scalar(select(Benchmark).where(Benchmark.symbol == symbol))

        if existing is not None and existing.provider_symbols is None:
            # See the sector branch above.
            existing.provider_symbols = provider_symbol_map(symbol, provider_symbol)
            existing.index_type = existing.index_type or "broad_market"
            if active and not existing.active:
                existing.active = True
                logger.info(
                    "activating benchmark %s: a configured provider now serves it", symbol
                )
            created["updated"] += 1

        if existing is None:
            session.add(
                Benchmark(
                    symbol=symbol,
                    benchmark_name=name,
                    display_name=display,
                    provider_symbol=provider_symbol,
                    provider_symbols=provider_symbol_map(symbol, provider_symbol),
                    exchange="NSE",
                    index_type="broad_market",
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
            existing.provider_symbols = provider_symbol_map(symbol, provider_symbol)
            existing.index_type = existing.index_type or "broad_market"
            existing.sort_order = order
            created["updated"] += 1

    logger.info("universe seeded: %s", created)
    return created


def _resolve(row, provider: str | None) -> str | None:
    """The identifier `provider` uses for this index, or None if it has none.

    Falls back to the legacy single `provider_symbol` column so rows seeded before
    `provider_symbols` existed keep working -- but only for Yahoo, since that column
    always held a Yahoo ticker. Handing a Yahoo ticker to NSE would make it search the
    archive for an index literally named "^CNXIT".
    """
    mapping = row.provider_symbols or {}
    if provider:
        value = mapping.get(provider)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            # Structured identifiers (Dhan: security_id + exchange_segment) belong to
            # their own adapter, not to this flat-symbol path.
            return None
        if provider in NAMESPACED_PROVIDERS:
            return None
    if row.provider_symbol.startswith(UNAVAILABLE_PREFIX):
        return None
    return row.provider_symbol


def ingestable_symbols(session: Session, provider: str | None = None) -> dict[str, str]:
    """{canonical symbol: provider symbol} for every active row this provider can serve.

    Indices the provider has no identifier for are omitted rather than attempted, so a
    missing mapping shows up as a smaller universe rather than a pile of per-symbol errors.
    """
    if provider is None:
        from .config import get_settings

        provider = get_settings().data_provider

    out: dict[str, str] = {}
    for sector in session.scalars(select(Sector).where(Sector.active.is_(True))):
        resolved = _resolve(sector, provider)
        if resolved:
            out[sector.symbol] = resolved
    for benchmark in session.scalars(select(Benchmark).where(Benchmark.active.is_(True))):
        resolved = _resolve(benchmark, provider)
        if resolved:
            out[benchmark.symbol] = resolved
    return out
