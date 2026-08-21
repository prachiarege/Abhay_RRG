"""NSE archive parsing and multi-source merging (V2-DATA-002).

No network: the archive parser is exercised against a fixture of the real CSV shape, and
the merge is exercised against rows written straight into the database. Both are the pieces
that decide what the engine actually sees, so they are worth pinning precisely.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="rrg_nse_test_"))
os.environ.setdefault("RRG_DATABASE_URL", f"sqlite:///{(_TMP / 'nse.db').as_posix()}")

from app.providers.nse import NSEProvider, _normalise_index_name  # noqa: E402

# A trimmed copy of the real file's shape, including the quirks that matter: mixed
# "Nifty"/"NIFTY" casing, thousands separators, and a "-" for an absent value.
ARCHIVE_CSV = """Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield
Nifty 50,20-08-2026,24100.10,24250.00,24050.00,24231.85,153.55,0.64,"1,234,567","98,765.43",22.5,4.1,1.2
Nifty 500,20-08-2026,"23,475.35","23,488.25","23,348.30","23,386.20",-86.20,-0.37,"2,345,678","12,345.67",24.1,4.3,1.1
NIFTY Auto,20-08-2026,"29,224.10","29,317.00","29,076.70","29,185.40",-79.15,-0.27,"345,678","5,432.10",26.0,5.2,0.9
Nifty Oil & Gas,20-08-2026,11500.00,11600.00,11450.00,11555.55,55.55,0.48,-,-,15.0,2.0,3.1
Nifty Broken,20-08-2026,-,-,-,-,-,-,-,-,-,-,-
"""


@pytest.fixture
def provider(tmp_path) -> NSEProvider:
    p = NSEProvider(cache_dir=tmp_path / "archive")
    # Isolate the class-level cache between tests.
    NSEProvider._memory_cache = {}
    return p


def test_parses_the_real_column_layout(provider: NSEProvider):
    parsed = provider._parse_day(ARCHIVE_CSV)

    nifty500 = parsed[_normalise_index_name("Nifty 500")]
    assert nifty500["close"] == pytest.approx(23386.20)
    assert nifty500["open"] == pytest.approx(23475.35)
    assert nifty500["high"] == pytest.approx(23488.25)
    assert nifty500["low"] == pytest.approx(23348.30)
    assert nifty500["date"] == pd.Timestamp("2026-08-20")


def test_thousands_separators_are_handled(provider: NSEProvider):
    """The archive quotes large numbers with commas; naive float() would raise."""
    parsed = provider._parse_day(ARCHIVE_CSV)
    assert parsed[_normalise_index_name("NIFTY Auto")]["close"] == pytest.approx(29185.40)


def test_index_name_matching_is_case_and_space_insensitive(provider: NSEProvider):
    """The archive writes "NIFTY Auto" here and "Nifty Auto" elsewhere; configuration may
    hold either. Matching on a folded key avoids a whole class of silent misses."""
    parsed = provider._parse_day(ARCHIVE_CSV)
    for spelling in ("Nifty Auto", "NIFTY AUTO", "nifty  auto", "NiftyAuto"):
        assert _normalise_index_name(spelling) in parsed, spelling


def test_ampersand_names_survive(provider: NSEProvider):
    parsed = provider._parse_day(ARCHIVE_CSV)
    assert parsed[_normalise_index_name("Nifty Oil & Gas")]["close"] == pytest.approx(11555.55)


def test_rows_with_no_close_are_dropped(provider: NSEProvider):
    """A row of dashes must not become a zero-valued bar -- that would read as a 100% fall."""
    parsed = provider._parse_day(ARCHIVE_CSV)
    assert _normalise_index_name("Nifty Broken") not in parsed


def test_absent_volume_becomes_none_not_zero(provider: NSEProvider):
    parsed = provider._parse_day(ARCHIVE_CSV)
    assert parsed[_normalise_index_name("Nifty Oil & Gas")]["volume"] is None


def test_series_assembly_from_day_files(provider: NSEProvider):
    """Several day-files collapse into one ascending series for a single index."""
    days = {
        date(2026, 8, 18): provider._parse_day(ARCHIVE_CSV.replace("20-08-2026", "18-08-2026")),
        date(2026, 8, 19): provider._parse_day(ARCHIVE_CSV.replace("20-08-2026", "19-08-2026")),
        date(2026, 8, 20): provider._parse_day(ARCHIVE_CSV),
    }
    frame = provider._series_from_days("Nifty 500", days)
    assert len(frame) == 3
    assert list(frame.frame.index) == sorted(frame.frame.index)
    assert frame.source == "nse"


def test_unknown_index_reports_clearly(provider: NSEProvider):
    from app.providers.base import ProviderError

    days = {date(2026, 8, 20): provider._parse_day(ARCHIVE_CSV)}
    with pytest.raises(ProviderError, match="no rows for"):
        provider._series_from_days("Nifty Nonexistent", days)


def test_cache_file_is_reused(provider: NSEProvider, tmp_path):
    """A cached day must not be re-downloaded -- the backfill relies on this."""
    day = date(2026, 8, 20)
    provider._cache_path(day).write_text(ARCHIVE_CSV, encoding="utf-8")
    # No network call happens; if one were attempted the test host might not have access.
    parsed = provider._day(day)
    assert parsed is not None
    assert _normalise_index_name("Nifty 500") in parsed


def test_truncated_cache_is_not_trusted(provider: NSEProvider):
    """A half-written cache file is worse than none, so it must not be served."""
    day = date(2026, 8, 20)
    provider._cache_path(day).write_text("Index Name,Index Date\n", encoding="utf-8")
    assert len(provider._cache_path(day).read_text(encoding="utf-8")) < 500


# --------------------------------------------------------------- multi-source merging


def test_merge_prefers_higher_priority_source_per_date():
    """Where two providers both have a date, the higher-priority one wins."""
    from app.db import init_db, session_scope
    from app.models import PriceData
    from app.services.ingestion import load_close_series, source_breakdown

    init_db()
    symbol = "TEST_MERGE"
    with session_scope() as session:
        session.query(PriceData).filter(PriceData.symbol == symbol).delete()
        for day, close, source in (
            (date(2026, 8, 17), 100.0, "yahoo"),
            (date(2026, 8, 18), 101.0, "yahoo"),
            # NSE disagrees on the 18th and uniquely covers the 19th.
            (date(2026, 8, 18), 999.0, "nse"),
            (date(2026, 8, 19), 103.0, "nse"),
        ):
            session.add(
                PriceData(symbol=symbol, date=day, source=source, close=close)
            )
        session.commit()

        merged = load_close_series(session, symbol, priority=["nse", "yahoo"])
        assert len(merged) == 3
        # NSE wins the contested date...
        assert merged.loc[pd.Timestamp("2026-08-18")] == pytest.approx(999.0)
        # ...and Yahoo still supplies the date NSE lacks.
        assert merged.loc[pd.Timestamp("2026-08-17")] == pytest.approx(100.0)

        # Reversing the priority flips only the contested date.
        flipped = load_close_series(session, symbol, priority=["yahoo", "nse"])
        assert flipped.loc[pd.Timestamp("2026-08-18")] == pytest.approx(101.0)
        assert flipped.loc[pd.Timestamp("2026-08-19")] == pytest.approx(103.0)

        # Provenance is reported as CONTRIBUTION, not raw row counts: NSE has two rows but
        # only contributes the two dates it wins.
        breakdown = source_breakdown(session, symbol, priority=["nse", "yahoo"])
        assert breakdown == {"nse": 2, "yahoo": 1}

        session.query(PriceData).filter(PriceData.symbol == symbol).delete()
        session.commit()


def test_pinning_to_one_source_ignores_the_others():
    """`source=` must give exactly that provider's view, for reproducibility work."""
    from app.db import init_db, session_scope
    from app.models import PriceData
    from app.services.ingestion import load_close_series

    init_db()
    symbol = "TEST_PIN"
    with session_scope() as session:
        session.query(PriceData).filter(PriceData.symbol == symbol).delete()
        session.add(PriceData(symbol=symbol, date=date(2026, 8, 17), source="yahoo", close=1.0))
        session.add(PriceData(symbol=symbol, date=date(2026, 8, 18), source="nse", close=2.0))
        session.commit()

        assert list(load_close_series(session, symbol, source="yahoo")) == [1.0]
        assert list(load_close_series(session, symbol, source="nse")) == [2.0]
        assert len(load_close_series(session, symbol)) == 2

        session.query(PriceData).filter(PriceData.symbol == symbol).delete()
        session.commit()


def test_namespaced_providers_do_not_inherit_yahoo_tickers():
    """Regression: NSE must never be handed "^CNXIT" as an index name.

    The fallback to the legacy `provider_symbol` column exists for providers that accept a
    generic symbol (Yahoo, CSV). Extending it to NSE or Dhan would make them search their
    own namespace for a foreign identifier.
    """
    from app.seed import NAMESPACED_PROVIDERS, _resolve

    class Row:
        provider_symbol = "^CNXIT"
        provider_symbols = {"yahoo": "^CNXIT"}

    assert _resolve(Row(), "yahoo") == "^CNXIT"
    assert _resolve(Row(), "csv") == "^CNXIT"  # file provider keys on a filename
    assert _resolve(Row(), "nse") is None
    assert _resolve(Row(), "dhan") is None
    assert {"nse", "dhan"} <= NAMESPACED_PROVIDERS
