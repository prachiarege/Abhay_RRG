"""Data provider abstraction (SRS 5.4, 50.4).

The calculation engine never imports a provider. It receives pandas Series. That is the
whole point of this layer: swapping the vendor must not touch a line of RRG maths.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date

import pandas as pd


class ProviderError(RuntimeError):
    """Raised when a provider cannot satisfy a request.

    Callers are expected to catch this per-symbol so that one bad sector cannot take
    down the whole chart (SRS 46).
    """


@dataclass(frozen=True)
class OHLCFrame:
    """A provider's answer for one symbol."""

    symbol: str
    frame: pd.DataFrame  # DatetimeIndex, columns: open/high/low/close/volume
    source: str

    @property
    def close(self) -> pd.Series:
        return self.frame["close"]

    def __len__(self) -> int:
        return len(self.frame)


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def normalise_frame(frame: pd.DataFrame, symbol: str, source: str) -> OHLCFrame:
    """Coerce a provider's raw output into the canonical shape.

    Enforces: DatetimeIndex normalised to midnight, ascending, no duplicate dates
    (last wins), all five columns present, close non-null and positive.
    """
    if frame is None or frame.empty:
        raise ProviderError(f"{source}: no data returned for {symbol}")

    work = frame.copy()
    work.columns = [str(c).strip().lower().replace(" ", "_") for c in work.columns]

    if "close" not in work.columns:
        if "adj_close" in work.columns:
            work["close"] = work["adj_close"]
        else:
            raise ProviderError(f"{source}: no close column for {symbol}")

    for column in REQUIRED_COLUMNS:
        if column not in work.columns:
            work[column] = pd.NA

    if not isinstance(work.index, pd.DatetimeIndex):
        work.index = pd.to_datetime(work.index, errors="coerce", utc=False)
    work = work[work.index.notna()]
    # Providers sometimes return tz-aware stamps; RRG is a daily-bar product, so the
    # time component is dropped rather than carried around and half-respected.
    if getattr(work.index, "tz", None) is not None:
        work.index = work.index.tz_localize(None)
    work.index = work.index.normalize()
    work = work[~work.index.duplicated(keep="last")].sort_index()

    numeric = work[list(REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    numeric = numeric[numeric["close"].notna() & (numeric["close"] > 0)]
    if numeric.empty:
        raise ProviderError(f"{source}: all close values invalid for {symbol}")

    numeric.index.name = "date"
    return OHLCFrame(symbol=symbol, frame=numeric, source=source)


class DataProvider(ABC):
    """Contract every provider implements."""

    name: str = "abstract"

    @abstractmethod
    def fetch(
        self,
        provider_symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> OHLCFrame:
        """Daily OHLCV for one symbol. Raises ProviderError on failure."""

    #: Concurrent fetches. Vendor calls are latency-bound, not CPU-bound, so serial
    #: fetching wastes almost all of the wall time waiting. Kept modest deliberately: a
    #: free endpoint will rate-limit or start refusing connections if hit hard, and a
    #: throttled fetch that fails is worse than a slower one that works.
    max_workers: int = 6

    def fetch_many(
        self,
        provider_symbols: dict[str, str],
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[dict[str, OHLCFrame], dict[str, str]]:
        """Fetch several symbols concurrently, isolating failures.

        Args:
            provider_symbols: {canonical_symbol: provider_symbol}

        Returns:
            (successes keyed by canonical symbol, {canonical symbol: error message}).
            Partial success is the normal case, not an exception -- SRS 46 requires one
            unavailable sector to leave the others working.

        Only the network calls run in parallel. Nothing here touches the database: callers
        persist the returned frames on their own thread, because a SQLAlchemy Session is not
        safe to share across threads.
        """
        results: dict[str, OHLCFrame] = {}
        errors: dict[str, str] = {}

        def one(canonical: str, provider_symbol: str) -> tuple[str, OHLCFrame | None, str | None]:
            try:
                return canonical, self.fetch(provider_symbol, start=start, end=end), None
            except ProviderError as exc:
                return canonical, None, str(exc)
            except Exception as exc:  # noqa: BLE001 - vendor libraries raise anything
                return canonical, None, f"{type(exc).__name__}: {exc}"

        workers = min(self.max_workers, max(1, len(provider_symbols)))
        if workers == 1 or len(provider_symbols) == 1:
            for canonical, provider_symbol in provider_symbols.items():
                _, frame, error = one(canonical, provider_symbol)
                if frame is not None:
                    results[canonical] = frame
                else:
                    errors[canonical] = error or "unknown error"
            return results, errors

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch") as pool:
            futures = [
                pool.submit(one, canonical, provider_symbol)
                for canonical, provider_symbol in provider_symbols.items()
            ]
            for future in as_completed(futures):
                canonical, frame, error = future.result()
                if frame is not None:
                    results[canonical] = frame
                else:
                    errors[canonical] = error or "unknown error"

        return results, errors

    def health(self) -> dict:
        return {"provider": self.name, "status": "unknown"}
