"""Data provider abstraction (SRS 5.4, 50.4).

The calculation engine never imports a provider. It receives pandas Series. That is the
whole point of this layer: swapping the vendor must not touch a line of RRG maths.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
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

    def fetch_many(
        self,
        provider_symbols: dict[str, str],
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[dict[str, OHLCFrame], dict[str, str]]:
        """Fetch several symbols, isolating failures.

        Args:
            provider_symbols: {canonical_symbol: provider_symbol}

        Returns:
            (successes keyed by canonical symbol, {canonical symbol: error message}).
            Partial success is the normal case, not an exception -- SRS 46 requires one
            unavailable sector to leave the others working.
        """
        results: dict[str, OHLCFrame] = {}
        errors: dict[str, str] = {}
        for canonical, provider_symbol in provider_symbols.items():
            try:
                results[canonical] = self.fetch(provider_symbol, start=start, end=end)
            except ProviderError as exc:
                errors[canonical] = str(exc)
            except Exception as exc:  # noqa: BLE001 - vendor libraries raise anything
                errors[canonical] = f"{type(exc).__name__}: {exc}"
        return results, errors

    def health(self) -> dict:
        return {"provider": self.name, "status": "unknown"}
