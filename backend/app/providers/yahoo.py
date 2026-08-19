"""Yahoo Finance provider via yfinance.

LICENSING NOTE, deliberately loud: Yahoo's terms of service do not permit
redistribution or commercial use of this data. It is here because it makes the
application work today with no API key and no contract, which is exactly what a
development and evaluation build needs. Before this ships to paying users, a licensed
feed (NSE Data Services or a vendor) must replace it -- which is a config change plus
one new class in this package, by design.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from .base import DataProvider, OHLCFrame, ProviderError, normalise_frame

logger = logging.getLogger(__name__)


class YahooProvider(DataProvider):
    name = "yahoo"

    def __init__(self, history_years: int = 12, timeout: int = 30) -> None:
        self.history_years = history_years
        self.timeout = timeout

    def fetch(
        self,
        provider_symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> OHLCFrame:
        try:
            import yfinance
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("yfinance is not installed") from exc

        if start is None:
            start = date.today() - timedelta(days=int(self.history_years * 365.25))
        if end is None:
            # yfinance treats `end` as exclusive.
            end = date.today() + timedelta(days=1)

        try:
            raw = yfinance.download(
                provider_symbol,
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
                multi_level_index=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"yahoo: download failed for {provider_symbol}: {exc}") from exc

        if raw is None or len(raw) == 0:
            raise ProviderError(f"yahoo: empty response for {provider_symbol}")

        # yfinance returns a column MultiIndex when given a list, and sometimes even for
        # a single ticker depending on version. Flatten defensively.
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.droplevel(-1, axis=1)

        return normalise_frame(raw, symbol=provider_symbol, source=self.name)

    def health(self) -> dict:
        try:
            frame = self.fetch("^CRSLDX", start=date.today() - timedelta(days=14))
            return {
                "provider": self.name,
                "status": "ok",
                "probe_symbol": "^CRSLDX",
                "rows": len(frame),
                "last_date": frame.frame.index.max().strftime("%Y-%m-%d"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"provider": self.name, "status": "error", "detail": str(exc)}
