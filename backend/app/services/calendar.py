"""Indian market trading calendar (SRS 28).

Deliberate design choice: the AUTHORITATIVE trading calendar is derived from the
benchmark's own observed dates, not from a hard-coded holiday table. A hand-maintained
holiday list inevitably goes stale, and a stale list silently corrupts every downstream
calculation.

The holiday table in ``config/nse_holidays.json`` is used only for VALIDATION -- to
warn when the feed hands us a bar on a date that should not have traded, and to explain
expected gaps rather than flagging them as missing data. It ships with the fixed-date
national holidays only; the exchange publishes a fresh list each year and the file is
meant to be topped up annually. An empty or missing file degrades gracefully.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

def _config_path() -> Path:
    """Locate the holiday file in the source tree or inside a PyInstaller bundle.

    A user-supplied copy in the data directory wins, so the annual holiday update does not
    require rebuilding the executable.
    """
    from ..config import DATA_ROOT, bundle_root

    user_copy = DATA_ROOT / "nse_holidays.json"
    if user_copy.exists():
        return user_copy
    return bundle_root() / "config" / "nse_holidays.json"


CONFIG_PATH = _config_path()

# Fixed-date national holidays that fall on the same calendar day every year and on
# which NSE does not trade. Movable feasts (Diwali, Holi, Eid, Good Friday, and the
# rest) vary annually and are NOT guessed here -- they belong in the JSON file.
FIXED_HOLIDAYS: tuple[tuple[int, int], ...] = (
    (1, 26),   # Republic Day
    (5, 1),    # Maharashtra Day
    (8, 15),   # Independence Day
    (10, 2),   # Gandhi Jayanti
    (12, 25),  # Christmas
)


@lru_cache(maxsize=1)
def load_holidays() -> frozenset[date]:
    """Load the maintained holiday list. Absent file is not an error."""
    holidays: set[date] = set()
    if CONFIG_PATH.exists():
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for entry in payload.get("holidays", []):
                holidays.add(pd.Timestamp(entry).date())
        except (ValueError, OSError) as exc:
            logger.warning("could not read holiday config %s: %s", CONFIG_PATH, exc)
    else:
        logger.info(
            "no holiday config at %s; relying on benchmark dates for the calendar",
            CONFIG_PATH,
        )
    return frozenset(holidays)


def is_weekend(when: date) -> bool:
    return pd.Timestamp(when).weekday() >= 5


def is_fixed_holiday(when: date) -> bool:
    return (when.month, when.day) in FIXED_HOLIDAYS


def is_expected_non_trading_day(when: date) -> bool:
    """True when this date is known not to be a trading session.

    Used to suppress spurious "missing data" warnings. Returning False does NOT
    assert the market was open -- only that we have no record saying it was shut.
    """
    return is_weekend(when) or is_fixed_holiday(when) or when in load_holidays()


def trading_calendar(benchmark_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The authoritative session list: the benchmark's own observations."""
    idx = pd.DatetimeIndex(benchmark_dates).normalize().unique().sort_values()
    return idx


def suspicious_sessions(benchmark_dates: pd.DatetimeIndex) -> list[date]:
    """Benchmark bars landing on dates that should not have traded.

    A non-empty result means either the holiday table is out of date or the data feed
    is producing phantom bars. Either way it is worth a log line (SRS 27, 45).
    """
    out: list[date] = []
    for stamp in trading_calendar(benchmark_dates):
        when = stamp.date()
        if is_weekend(when) or is_fixed_holiday(when) or when in load_holidays():
            out.append(when)
    return out
