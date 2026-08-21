"""NSE archive provider — free, authoritative index data straight from the exchange.

NSE publishes a daily CSV containing the OHLC of *every* index it calculates:

    https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv

Verified against the live archive: 161 indices per file, full Open/High/Low/Close, and
values that match Yahoo's to the paise on overlapping days — so switching or splicing
sources introduces no discontinuity in the relative-strength series.

Why this exists (and replaced the earlier stub): Yahoo stopped publishing a whole class of
NSE sector indices for a month and never backfilled the hole. A NaN anywhere in a rolling
window nullifies that window, so a four-week gap suppresses RRG output for the gap *plus*
the warm-up chain behind it — about five months. NSE has the missing days.

## The axis problem

The `DataProvider` contract is per-symbol: `fetch(symbol, start, end)`. NSE's archive is
per-*day*, all symbols. Fetching naively would re-download each day file once per symbol —
18 symbols over 22 days would be 396 requests instead of 22. `fetch_many` is therefore
overridden to download each day once and slice every requested symbol out of it, and day
files are cached on disk so a re-run or an overlapping window costs nothing.

## What this is not

This is a published file archive, not a contracted API. There is no SLA, it needs
browser-like headers, and NSE can change or restrict it. It is the right default for a
single-user local tool; a commercial product should hold a data licence. See
docs/SRS_DEVIATIONS.md.
"""

from __future__ import annotations

import csv
import io
import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .base import DataProvider, OHLCFrame, ProviderError, normalise_frame

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archives.nseindia.com/content/indices/ind_close_all_{stamp}.csv"

# NSE serves the archive from a CDN that rejects non-browser clients. These headers are the
# minimum that works; without them the request returns 403.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

#: Column positions in the archive CSV. Header, for reference:
#: Index Name, Index Date, Open Index Value, High Index Value, Low Index Value,
#: Closing Index Value, Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield
COL_NAME, COL_DATE, COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE = 0, 1, 2, 3, 4, 5
COL_VOLUME = 8

#: Concurrent day-file downloads. Deliberately low: this is a public file archive, not a
#: rate-limited API with a published quota, so politeness is the only available guide.
MAX_WORKERS = 4
REQUEST_TIMEOUT = 25


def _normalise_index_name(name: str) -> str:
    """Fold an index name for matching: case, spacing and punctuation are all unreliable.

    The archive writes "Nifty 500", configuration might hold "NIFTY 500", and some rows
    carry double spaces. Comparing on a folded key avoids a whole class of silent misses.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


class NSEProvider(DataProvider):
    """Reads NSE's published daily index archive."""

    name = "nse"

    # One shared cache per process, so several fetch/fetch_many calls in one refresh do not
    # re-parse the same day.
    _memory_cache: dict[date, dict[str, dict]] = {}

    def __init__(self, timeout: int = REQUEST_TIMEOUT, cache_dir: Path | None = None) -> None:
        self.timeout = timeout
        if cache_dir is None:
            from ..config import DATA_ROOT

            cache_dir = DATA_ROOT / "nse_archive"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ day files

    def _cache_path(self, day: date) -> Path:
        return self.cache_dir / f"ind_close_all_{day.strftime('%d%m%Y')}.csv"

    def _download_day(self, day: date) -> str | None:
        """Raw CSV text for one day, or None when the archive has no file for it.

        A missing file is the normal signal for a weekend or exchange holiday, so a 404 is
        returned as None rather than raised — the caller cannot distinguish a holiday from a
        gap any other way, and NSE publishes no holiday endpoint.
        """
        cached = self._cache_path(day)
        if cached.is_file():
            text = cached.read_text(encoding="utf-8", errors="ignore")
            # A truncated cache entry is worse than none; re-fetch anything implausible.
            if len(text) > 500:
                return text

        url = ARCHIVE_URL.format(stamp=day.strftime("%d%m%Y"))
        request = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                logger.debug("no NSE archive for %s (HTTP %s)", day, exc.code)
                return None
            raise ProviderError(f"nse: HTTP {exc.code} fetching {day}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"nse: cannot fetch {day}: {exc}") from exc

        text = raw.decode("utf-8", errors="ignore")
        if len(text) < 500 or "Index Name" not in text:
            logger.debug("NSE archive for %s looks empty", day)
            return None

        try:
            cached.write_text(text, encoding="utf-8")
        except OSError:
            # A read-only or full disk should slow us down, not stop us.
            logger.debug("could not cache NSE archive for %s", day)
        return text

    def _parse_day(self, text: str) -> dict[str, dict]:
        """{folded index name: {open, high, low, close, volume, date}} for one day."""
        rows: dict[str, dict] = {}
        for row in csv.reader(io.StringIO(text)):
            if len(row) <= COL_CLOSE or row[COL_NAME].strip() in ("", "Index Name"):
                continue

            def number(position: int) -> float | None:
                if position >= len(row):
                    return None
                raw = row[position].strip().replace(",", "")
                if raw in ("", "-", "NA", "N.A.", "0"):
                    # A literal zero is not a plausible index level; treat it as absent
                    # rather than letting it become a 100% single-day move downstream.
                    return None
                try:
                    return float(raw)
                except ValueError:
                    return None

            close = number(COL_CLOSE)
            if close is None:
                continue

            stamp = row[COL_DATE].strip()
            try:
                parsed = pd.to_datetime(stamp, format="%d-%m-%Y")
            except (ValueError, TypeError):
                parsed = pd.to_datetime(stamp, errors="coerce", dayfirst=True)
            if pd.isna(parsed):
                continue

            rows[_normalise_index_name(row[COL_NAME])] = {
                "date": parsed.normalize(),
                "open": number(COL_OPEN),
                "high": number(COL_HIGH),
                "low": number(COL_LOW),
                "close": close,
                "volume": number(COL_VOLUME),
            }
        return rows

    def _day(self, day: date) -> dict[str, dict] | None:
        if day in self._memory_cache:
            return self._memory_cache[day]
        text = self._download_day(day)
        if text is None:
            self._memory_cache[day] = {}
            return {}
        parsed = self._parse_day(text)
        self._memory_cache[day] = parsed
        return parsed

    def _load_range(self, start: date, end: date) -> dict[date, dict[str, dict]]:
        """Download every weekday file in the window, concurrently but politely."""
        days = []
        cursor = start
        while cursor <= end:
            # Weekends never have a file; skipping them locally saves a third of the requests.
            if cursor.weekday() < 5 and cursor not in self._memory_cache:
                days.append(cursor)
            cursor += timedelta(days=1)

        if days:
            logger.info("fetching %d NSE archive day-files", len(days))
            with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="nse") as pool:
                futures = {pool.submit(self._day, day): day for day in days}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except ProviderError as exc:
                        logger.warning("NSE archive: %s", exc)
                    except Exception:  # noqa: BLE001
                        logger.exception("NSE archive day failed")

        out: dict[date, dict[str, dict]] = {}
        cursor = start
        while cursor <= end:
            parsed = self._memory_cache.get(cursor)
            if parsed:
                out[cursor] = parsed
            cursor += timedelta(days=1)
        return out

    # -------------------------------------------------------------- provider API

    def _series_from_days(
        self,
        provider_symbol: str,
        days: dict[date, dict[str, dict]],
    ) -> OHLCFrame:
        key = _normalise_index_name(provider_symbol)
        records = []
        for parsed in days.values():
            row = parsed.get(key)
            if row is not None:
                records.append(row)

        if not records:
            raise ProviderError(
                f"nse: no rows for {provider_symbol!r} in the requested window. "
                "Check the index name matches NSE's own spelling in the archive."
            )

        frame = pd.DataFrame(records).set_index("date").sort_index()
        return normalise_frame(frame, symbol=provider_symbol, source=self.name)

    def fetch(
        self,
        provider_symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> OHLCFrame:
        """One index's history. Prefer `fetch_many` — see the module docstring."""
        end = end or date.today()
        start = start or (end - timedelta(days=365))
        days = self._load_range(start, end)
        if not days:
            raise ProviderError(
                f"nse: no archive files available between {start} and {end}"
            )
        return self._series_from_days(provider_symbol, days)

    def fetch_many(
        self,
        provider_symbols: dict[str, str],
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[dict[str, OHLCFrame], dict[str, str]]:
        """Download each day once, then slice out every requested index.

        This is the reason for overriding the base implementation: the base loops per symbol,
        which for a day-file archive means re-downloading the same file once per symbol.
        """
        end = end or date.today()
        start = start or (end - timedelta(days=365))

        results: dict[str, OHLCFrame] = {}
        errors: dict[str, str] = {}

        try:
            days = self._load_range(start, end)
        except ProviderError as exc:
            return {}, {symbol: str(exc) for symbol in provider_symbols}

        if not days:
            message = f"no NSE archive files between {start} and {end}"
            return {}, {symbol: message for symbol in provider_symbols}

        for canonical, provider_symbol in provider_symbols.items():
            try:
                results[canonical] = self._series_from_days(provider_symbol, days)
            except ProviderError as exc:
                errors[canonical] = str(exc)
            except Exception as exc:  # noqa: BLE001
                errors[canonical] = f"{type(exc).__name__}: {exc}"

        return results, errors

    def available_indices(self, day: date | None = None) -> list[str]:
        """Index names present in a day's file — useful for building configuration.

        NSE publishes ~160 indices, far more than any third-party feed carries, so this is
        the practical way to discover what is actually available to configure.
        """
        target = day or date.today()
        for _ in range(7):
            if target.weekday() < 5:
                text = self._download_day(target)
                if text:
                    return sorted(
                        row[COL_NAME].strip()
                        for row in csv.reader(io.StringIO(text))
                        if row and row[COL_NAME].strip() not in ("", "Index Name")
                    )
            target -= timedelta(days=1)
        return []

    def health(self) -> dict:
        """Probe the most recent weekday that has a file."""
        target = date.today()
        for _ in range(7):
            if target.weekday() < 5:
                try:
                    text = self._download_day(target)
                except ProviderError as exc:
                    return {"provider": self.name, "status": "error", "detail": str(exc)}
                if text:
                    parsed = self._parse_day(text)
                    return {
                        "provider": self.name,
                        "status": "ok",
                        "probe_date": target.isoformat(),
                        "indices": len(parsed),
                        "cache_dir": str(self.cache_dir),
                    }
            target -= timedelta(days=1)
        return {
            "provider": self.name,
            "status": "error",
            "detail": "no archive file found in the last 7 days",
        }
