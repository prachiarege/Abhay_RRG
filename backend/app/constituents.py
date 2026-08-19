"""Index constituents — the sector-to-stock membership used for drill-down.

**Important limitation, stated up front.** This is a point-in-time snapshot of index
membership, not a historical record. NSE rebalances its indices, so a stock-level RRG drawn
over two years using *today's* constituents carries composition bias: it shows how today's
members behaved historically, silently excluding anything that has since been removed. That
is the same family of problem as look-ahead bias, and it is not fixable with a static list.

The application therefore:

*   records `as_of` on every membership row, and exposes it in the API so the UI can say
    which snapshot is being used;
*   keeps membership in the database, not in code, so a fresh snapshot can be imported
    without a release;
*   does not claim the stock-level historical view is survivorship-free.

For an accurate historical study you need dated membership history from a licensed vendor.
For "which stocks in this sector are leading right now" -- the actual use case -- a current
snapshot is the correct input.

Membership below reflects NSE index composition as of the `AS_OF` date. Update it by
editing this file and re-seeding, or by importing a CSV of NSE's published index files.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Sector, Stock

logger = logging.getLogger(__name__)

AS_OF = date(2026, 8, 1)

# Distinct hues cycled per sector so constituents are visually separable on the plot.
# Deliberately not semantic: a stock's colour carries no meaning beyond identity.
STOCK_PALETTE: tuple[str, ...] = (
    "#22c55e", "#3b82f6", "#f59e0b", "#a855f7", "#06b6d4",
    "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#818cf8",
    "#eab308", "#f43f5e", "#4ade80", "#60a5fa", "#c084fc",
    "#fb923c", "#2dd4bf", "#facc15", "#fb7185", "#a3e635",
)

# {sector symbol: ((nse_symbol, company name), ...)}
# NSE symbol is the canonical identity; the Yahoo provider symbol is "<symbol>.NS".
CONSTITUENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "NIFTY_IT": (
        ("TCS", "Tata Consultancy Services"),
        ("INFY", "Infosys"),
        ("HCLTECH", "HCL Technologies"),
        ("WIPRO", "Wipro"),
        ("TECHM", "Tech Mahindra"),
        ("LTIM", "LTIMindtree"),
        ("PERSISTENT", "Persistent Systems"),
        ("COFORGE", "Coforge"),
        ("MPHASIS", "Mphasis"),
        ("OFSS", "Oracle Financial Services"),
    ),
    "NIFTY_BANK": (
        ("HDFCBANK", "HDFC Bank"),
        ("ICICIBANK", "ICICI Bank"),
        ("SBIN", "State Bank of India"),
        ("KOTAKBANK", "Kotak Mahindra Bank"),
        ("AXISBANK", "Axis Bank"),
        ("INDUSINDBK", "IndusInd Bank"),
        ("BANKBARODA", "Bank of Baroda"),
        ("PNB", "Punjab National Bank"),
        ("IDFCFIRSTB", "IDFC First Bank"),
        ("AUBANK", "AU Small Finance Bank"),
        ("FEDERALBNK", "Federal Bank"),
        ("CANBK", "Canara Bank"),
    ),
    "NIFTY_AUTO": (
        ("M&M", "Mahindra & Mahindra"),
        ("MARUTI", "Maruti Suzuki"),
        ("TMPV", "Tata Motors Passenger Vehicles"),
        ("BAJAJ-AUTO", "Bajaj Auto"),
        ("EICHERMOT", "Eicher Motors"),
        ("HEROMOTOCO", "Hero MotoCorp"),
        ("TVSMOTOR", "TVS Motor"),
        ("ASHOKLEY", "Ashok Leyland"),
        ("BHARATFORG", "Bharat Forge"),
        ("BOSCHLTD", "Bosch"),
        ("MRF", "MRF"),
        ("BALKRISIND", "Balkrishna Industries"),
        ("EXIDEIND", "Exide Industries"),
        ("MOTHERSON", "Samvardhana Motherson"),
        ("TIINDIA", "Tube Investments of India"),
    ),
    "NIFTY_FMCG": (
        ("ITC", "ITC"),
        ("HINDUNILVR", "Hindustan Unilever"),
        ("NESTLEIND", "Nestle India"),
        ("VBL", "Varun Beverages"),
        ("BRITANNIA", "Britannia Industries"),
        ("GODREJCP", "Godrej Consumer Products"),
        ("TATACONSUM", "Tata Consumer Products"),
        ("DABUR", "Dabur India"),
        ("MARICO", "Marico"),
        ("COLPAL", "Colgate-Palmolive India"),
        ("UNITDSPR", "United Spirits"),
        ("PATANJALI", "Patanjali Foods"),
        ("RADICO", "Radico Khaitan"),
        ("EMAMILTD", "Emami"),
        ("UBL", "United Breweries"),
    ),
    "NIFTY_PHARMA": (
        ("SUNPHARMA", "Sun Pharmaceutical"),
        ("CIPLA", "Cipla"),
        ("DRREDDY", "Dr Reddy's Laboratories"),
        ("DIVISLAB", "Divi's Laboratories"),
        ("TORNTPHARM", "Torrent Pharmaceuticals"),
        ("ZYDUSLIFE", "Zydus Lifesciences"),
        ("LUPIN", "Lupin"),
        ("AUROPHARMA", "Aurobindo Pharma"),
        ("ALKEM", "Alkem Laboratories"),
        ("MANKIND", "Mankind Pharma"),
        ("GLENMARK", "Glenmark Pharmaceuticals"),
        ("IPCALAB", "IPCA Laboratories"),
        ("ABBOTINDIA", "Abbott India"),
        ("BIOCON", "Biocon"),
        ("LAURUSLABS", "Laurus Labs"),
        ("GRANULES", "Granules India"),
        ("NATCOPHARM", "Natco Pharma"),
        ("AJANTPHARM", "Ajanta Pharma"),
        ("JBCHEPHARM", "JB Chemicals"),
    ),
    "NIFTY_METAL": (
        ("TATASTEEL", "Tata Steel"),
        ("HINDALCO", "Hindalco Industries"),
        ("JSWSTEEL", "JSW Steel"),
        ("VEDL", "Vedanta"),
        ("JINDALSTEL", "Jindal Steel & Power"),
        ("SAIL", "Steel Authority of India"),
        ("NMDC", "NMDC"),
        ("NATIONALUM", "National Aluminium"),
        ("APLAPOLLO", "APL Apollo Tubes"),
        ("HINDZINC", "Hindustan Zinc"),
        ("HINDCOPPER", "Hindustan Copper"),
        ("JSL", "Jindal Stainless"),
        ("WELCORP", "Welspun Corp"),
        ("LLOYDSME", "Lloyds Metals & Energy"),
        ("ADANIENT", "Adani Enterprises"),
    ),
    "NIFTY_REALTY": (
        ("DLF", "DLF"),
        ("LODHA", "Lodha Developers"),
        ("GODREJPROP", "Godrej Properties"),
        ("OBEROIRLTY", "Oberoi Realty"),
        ("PHOENIXLTD", "Phoenix Mills"),
        ("PRESTIGE", "Prestige Estates"),
        ("BRIGADE", "Brigade Enterprises"),
        ("SOBHA", "Sobha"),
        ("ANANTRAJ", "Anant Raj"),
        ("RAYMOND", "Raymond"),
    ),
    "NIFTY_MEDIA": (
        ("ZEEL", "Zee Entertainment"),
        ("SUNTV", "Sun TV Network"),
        ("PVRINOX", "PVR INOX"),
        ("NAZARA", "Nazara Technologies"),
        ("SAREGAMA", "Saregama India"),
        ("TIPSMUSIC", "Tips Music"),
        ("DISHTV", "Dish TV India"),
        ("NETWORK18", "Network18 Media"),
        ("TV18BRDCST", "TV18 Broadcast"),
        ("HATHWAY", "Hathway Cable"),
    ),
    "NIFTY_ENERGY": (
        ("RELIANCE", "Reliance Industries"),
        ("ONGC", "Oil & Natural Gas Corporation"),
        ("NTPC", "NTPC"),
        ("POWERGRID", "Power Grid Corporation"),
        ("COALINDIA", "Coal India"),
        ("BPCL", "Bharat Petroleum"),
        ("IOC", "Indian Oil Corporation"),
        ("GAIL", "GAIL India"),
        ("TATAPOWER", "Tata Power"),
        ("ADANIGREEN", "Adani Green Energy"),
    ),
    "NIFTY_INFRA": (
        ("RELIANCE", "Reliance Industries"),
        ("LT", "Larsen & Toubro"),
        ("BHARTIARTL", "Bharti Airtel"),
        ("NTPC", "NTPC"),
        ("ONGC", "Oil & Natural Gas Corporation"),
        ("POWERGRID", "Power Grid Corporation"),
        ("ULTRACEMCO", "UltraTech Cement"),
        ("ADANIPORTS", "Adani Ports & SEZ"),
        ("GRASIM", "Grasim Industries"),
        ("COALINDIA", "Coal India"),
        ("IOC", "Indian Oil Corporation"),
        ("SHREECEM", "Shree Cement"),
        ("AMBUJACEM", "Ambuja Cements"),
        ("SIEMENS", "Siemens India"),
        ("ABB", "ABB India"),
    ),
    "NIFTY_FINSERV": (
        ("HDFCBANK", "HDFC Bank"),
        ("ICICIBANK", "ICICI Bank"),
        ("AXISBANK", "Axis Bank"),
        ("KOTAKBANK", "Kotak Mahindra Bank"),
        ("SBIN", "State Bank of India"),
        ("BAJFINANCE", "Bajaj Finance"),
        ("BAJAJFINSV", "Bajaj Finserv"),
        ("SBILIFE", "SBI Life Insurance"),
        ("HDFCLIFE", "HDFC Life Insurance"),
        ("SHRIRAMFIN", "Shriram Finance"),
        ("JIOFIN", "Jio Financial Services"),
        ("CHOLAFIN", "Cholamandalam Investment"),
        ("ICICIGI", "ICICI Lombard General Insurance"),
        ("ICICIPRULI", "ICICI Prudential Life"),
        ("HDFCAMC", "HDFC Asset Management"),
        ("LICI", "Life Insurance Corporation"),
        ("MUTHOOTFIN", "Muthoot Finance"),
        ("PFC", "Power Finance Corporation"),
        ("RECLTD", "REC"),
        ("SBICARD", "SBI Cards & Payment Services"),
    ),
    "NIFTY_PSU_BANK": (
        ("SBIN", "State Bank of India"),
        ("BANKBARODA", "Bank of Baroda"),
        ("PNB", "Punjab National Bank"),
        ("CANBK", "Canara Bank"),
        ("UNIONBANK", "Union Bank of India"),
        ("INDIANB", "Indian Bank"),
        ("BANKINDIA", "Bank of India"),
        ("CENTRALBK", "Central Bank of India"),
        ("IOB", "Indian Overseas Bank"),
        ("UCOBANK", "UCO Bank"),
        ("MAHABANK", "Bank of Maharashtra"),
        ("PSB", "Punjab & Sind Bank"),
    ),
    "NIFTY_PVT_BANK": (
        ("HDFCBANK", "HDFC Bank"),
        ("ICICIBANK", "ICICI Bank"),
        ("AXISBANK", "Axis Bank"),
        ("KOTAKBANK", "Kotak Mahindra Bank"),
        ("INDUSINDBK", "IndusInd Bank"),
        ("IDFCFIRSTB", "IDFC First Bank"),
        ("FEDERALBNK", "Federal Bank"),
        ("BANDHANBNK", "Bandhan Bank"),
        ("RBLBANK", "RBL Bank"),
        ("CUB", "City Union Bank"),
    ),
    "NIFTY_COMMODITIES": (
        ("RELIANCE", "Reliance Industries"),
        ("ULTRACEMCO", "UltraTech Cement"),
        ("TATASTEEL", "Tata Steel"),
        ("JSWSTEEL", "JSW Steel"),
        ("HINDALCO", "Hindalco Industries"),
        ("GRASIM", "Grasim Industries"),
        ("COALINDIA", "Coal India"),
        ("ONGC", "Oil & Natural Gas Corporation"),
        ("IOC", "Indian Oil Corporation"),
        ("BPCL", "Bharat Petroleum"),
        ("SHREECEM", "Shree Cement"),
        ("AMBUJACEM", "Ambuja Cements"),
        ("VEDL", "Vedanta"),
        ("PIIND", "PI Industries"),
        ("UPL", "UPL"),
    ),
}


# Where the provider's ticker does not follow the "<NSE symbol>.NS" rule. Empty today
# because the two known divergences were resolved by renaming the constituent itself
# (see below), but corporate actions produce these regularly, so the seam stays.
PROVIDER_OVERRIDES: dict[str, str] = {}

# Verified against the live provider on 2026-08-19: 148 of 153 unique tickers resolve.
# The rest are recorded here rather than quietly dropped, because index MEMBERSHIP is a
# real fact even when the provider has no series -- the app marks them unavailable on
# first fetch and the UI greys them out with a reason.
#
#   LTIM        LTIMindtree      no Yahoo series under any tried symbol
#   TV18BRDCST  TV18 Broadcast   no series; NETWORK18 (also a member) resolves
#
# Two others were provider-side ticker changes and are fixed above:
#   TATAMOTORS -> TMPV    the post-demerger passenger-vehicle entity
#   MACROTECH  -> LODHA   ticker renamed
KNOWN_UNAVAILABLE: frozenset[str] = frozenset({"LTIM", "TV18BRDCST"})


def provider_symbol_for(nse_symbol: str) -> str:
    """Provider ticker for an NSE-listed equity.

    Yahoo's NSE equity coverage is markedly better than its NSE sector-INDEX coverage, so
    stock-level drill-down is in practice more reliable and fresher than the sector view it
    drills into.
    """
    return PROVIDER_OVERRIDES.get(nse_symbol, f"{nse_symbol}.NS")


def seed_constituents(session: Session, overwrite: bool = False) -> dict[str, int]:
    """Insert the membership snapshot. Idempotent.

    A stock appearing in several sectors (HDFCBANK is in Bank, Financial Services and
    Private Bank) gets one row per membership, because membership is the fact being
    recorded, not the company.
    """
    created = 0
    updated = 0
    skipped_sectors: list[str] = []

    known_sectors = {
        row.symbol for row in session.scalars(select(Sector))
    }

    for sector_symbol, members in CONSTITUENTS.items():
        if sector_symbol not in known_sectors:
            skipped_sectors.append(sector_symbol)
            continue

        for position, (nse_symbol, company) in enumerate(members):
            existing = session.scalar(
                select(Stock).where(
                    Stock.sector_symbol == sector_symbol,
                    Stock.symbol == nse_symbol,
                )
            )
            colour = STOCK_PALETTE[position % len(STOCK_PALETTE)]
            if existing is None:
                session.add(
                    Stock(
                        symbol=nse_symbol,
                        company_name=company,
                        sector_symbol=sector_symbol,
                        provider_symbol=provider_symbol_for(nse_symbol),
                        exchange="NSE",
                        color=colour,
                        sort_order=position * 10,
                        as_of=AS_OF,
                        active=True,
                    )
                )
                created += 1
            elif overwrite:
                existing.company_name = company
                existing.provider_symbol = provider_symbol_for(nse_symbol)
                existing.color = colour
                existing.sort_order = position * 10
                existing.as_of = AS_OF
                updated += 1

    if skipped_sectors:
        logger.warning(
            "constituents defined for unknown sectors, skipped: %s",
            ", ".join(sorted(skipped_sectors)),
        )

    # Prune memberships that are no longer in the snapshot. Without this, seeding is purely
    # additive and every ticker change leaves a ghost behind -- a renamed constituent would
    # appear twice, once under its dead symbol permanently marked unavailable.
    #
    # Only sectors present in CONSTITUENTS are touched, so a manually added membership in
    # some other sector is never silently removed. Stored prices for a pruned symbol are
    # left alone: they are harmless, and keeping them means re-adding the stock costs no
    # download.
    removed = 0
    for sector_symbol, members in CONSTITUENTS.items():
        if sector_symbol not in known_sectors:
            continue
        current = {symbol for symbol, _name in members}
        for row in session.scalars(
            select(Stock).where(Stock.sector_symbol == sector_symbol)
        ):
            if row.symbol not in current:
                logger.info(
                    "pruning stale membership %s from %s", row.symbol, sector_symbol
                )
                session.delete(row)
                removed += 1

    result = {
        "created": created,
        "updated": updated,
        "removed": removed,
        "sectors": len(CONSTITUENTS),
    }
    logger.info("constituents seeded: %s", result)
    return result
