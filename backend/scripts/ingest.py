"""Command-line data ingestion.

    python -m scripts.ingest                    # full universe, provider's full window
    python -m scripts.ingest --symbols NIFTY_IT NIFTY500
    python -m scripts.ingest --years 5
    python -m scripts.ingest --provider csv
    python -m scripts.ingest --rotations        # also rescan quadrant transitions

Run from the backend/ directory with the virtualenv active.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.engine.params import RRGParams  # noqa: E402
from app.providers import get_provider  # noqa: E402
from app.seed import ingestable_symbols, seed_universe  # noqa: E402
from app.services.ingestion import data_freshness, refresh_prices  # noqa: E402
from app.services.rrg_service import persist_rotations  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
logger = logging.getLogger("ingest")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Indian index price history")
    parser.add_argument("--symbols", nargs="*", help="canonical symbols; default is all active")
    parser.add_argument("--years", type=float, default=None, help="history window in years")
    parser.add_argument("--from", dest="date_from", default=None, help="start date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", default=None, help="end date YYYY-MM-DD")
    parser.add_argument("--provider", default=None, help="yahoo | csv | nse")
    parser.add_argument("--rotations", action="store_true", help="rescan rotation events after")
    parser.add_argument("--reseed", action="store_true", help="refresh universe metadata first")
    args = parser.parse_args()

    settings = get_settings()
    init_db()

    provider = get_provider(args.provider)
    start = None
    end = None
    if args.date_from:
        start = date.fromisoformat(args.date_from)
    elif args.years:
        start = date.today() - timedelta(days=int(args.years * 365.25))
    if args.date_to:
        end = date.fromisoformat(args.date_to)

    with session_scope() as session:
        seed_universe(session, overwrite=args.reseed)
        session.commit()

        symbols = None
        if args.symbols:
            # Resolve against the provider actually being used, not the configured
            # default -- otherwise --provider nse --symbols X fails for any index that
            # only NSE carries.
            everything = ingestable_symbols(session, provider=provider.name)
            symbols = {k: v for k, v in everything.items() if k in set(args.symbols)}
            unknown = sorted(set(args.symbols) - set(symbols))
            if unknown:
                logger.error("unknown or unavailable symbols: %s", ", ".join(unknown))
                return 2

        if end is not None:
            # A bounded window is a backfill, so say so in the audit log rather than
            # recording it as a routine refresh.
            result = refresh_prices(
                session, provider=provider, symbols=symbols, start=start,
                end=end, trigger="backfill",
            )
        else:
            result = refresh_prices(
                session, provider=provider, symbols=symbols, start=start, trigger="cli"
            )

        print()
        print(f"provider     : {result.provider}")
        print(f"status       : {result.status}")
        print(f"succeeded    : {len(result.succeeded)}/{len(result.requested)}")
        print(f"rows written : {result.rows_written}")

        if result.failed:
            print("\nfailures:")
            for symbol, message in sorted(result.failed.items()):
                print(f"  {symbol:22s} {message}")

        warned = {
            symbol: report
            for symbol, report in result.reports.items()
            if report.gaps or report.suspected_spikes or report.weekend_or_holiday_rows
        }
        if warned:
            print("\ndata-quality warnings:")
            for symbol, report in sorted(warned.items()):
                bits = []
                if report.gaps:
                    bits.append(f"{len(report.gaps)} gaps")
                if report.suspected_spikes:
                    bits.append(f"{len(report.suspected_spikes)} spikes")
                if report.weekend_or_holiday_rows:
                    bits.append(f"{len(report.weekend_or_holiday_rows)} non-session bars")
                print(f"  {symbol:22s} {', '.join(bits)}")

        print("\ncoverage:")
        for symbol, report in sorted(result.reports.items()):
            print(
                f"  {symbol:22s} {report.rows:6d} bars  "
                f"{report.first_date} -> {report.last_date}"
            )

        if args.rotations:
            params = RRGParams(
                rs_period=settings.rs_period,
                momentum_period=settings.momentum_period,
                smoothing_period=settings.smoothing_period,
                smoothing_method=settings.smoothing_method,
            )
            print()
            for frequency in ("daily", "weekly"):
                count = persist_rotations(
                    session,
                    benchmark=settings.default_benchmark,
                    frequency=frequency,
                    params=params,
                )
                print(f"rotation events stored ({frequency}): {count}")

        freshness = data_freshness(session)
        print(f"\nlatest stored date: {freshness['latest_date']}")

    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
