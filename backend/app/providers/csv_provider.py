"""CSV provider -- deterministic, offline, licence-clean.

This is the provider tests run against and the one to use when a licensed vendor
delivers files rather than an API. It is also the escape hatch when Yahoo changes shape:
drop CSVs in the data directory, set RRG_DATA_PROVIDER=csv, and the app keeps working.

Expected layout: one file per symbol at ``<csv_dir>/<PROVIDER_SYMBOL>.csv`` with a
header row. Column names are matched case-insensitively and tolerate the common
variants (``Date``/``date``/``timestamp``, ``Close``/``close``/``Close Price``).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from .base import DataProvider, OHLCFrame, ProviderError, normalise_frame

logger = logging.getLogger(__name__)

DATE_ALIASES = ("date", "timestamp", "datetime", "trade_date")
CLOSE_ALIASES = ("close", "close_price", "closing_price", "last", "index_value", "value")


class CSVProvider(DataProvider):
    name = "csv"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _path_for(self, provider_symbol: str) -> Path:
        # Provider symbols may contain characters that are illegal in filenames
        # (Yahoo's leading caret, for one), so normalise before looking up.
        safe = provider_symbol.replace("^", "").replace("/", "_").replace("\\", "_")
        candidates = [
            self.directory / f"{provider_symbol}.csv",
            self.directory / f"{safe}.csv",
            self.directory / f"{safe.upper()}.csv",
            self.directory / f"{safe.lower()}.csv",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise ProviderError(
            f"csv: no file for {provider_symbol} in {self.directory} "
            f"(looked for {safe}.csv)"
        )

    def fetch(
        self,
        provider_symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> OHLCFrame:
        path = self._path_for(provider_symbol)
        try:
            raw = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"csv: cannot read {path}: {exc}") from exc

        lowered = {str(c).strip().lower(): c for c in raw.columns}

        date_column = next((lowered[a] for a in DATE_ALIASES if a in lowered), None)
        if date_column is None:
            raise ProviderError(f"csv: {path.name} has no recognisable date column")

        close_column = next((lowered[a] for a in CLOSE_ALIASES if a in lowered), None)
        if close_column is None:
            raise ProviderError(f"csv: {path.name} has no recognisable close column")

        work = raw.rename(columns={date_column: "date", close_column: "close"})
        work["date"] = pd.to_datetime(work["date"], errors="coerce", dayfirst=False)
        work = work.dropna(subset=["date"]).set_index("date")

        frame = normalise_frame(work, symbol=provider_symbol, source=self.name)

        if start is not None or end is not None:
            mask = pd.Series(True, index=frame.frame.index)
            if start is not None:
                mask &= frame.frame.index >= pd.Timestamp(start)
            if end is not None:
                mask &= frame.frame.index <= pd.Timestamp(end)
            trimmed = frame.frame[mask]
            if trimmed.empty:
                raise ProviderError(
                    f"csv: {provider_symbol} has no rows in the requested window"
                )
            return OHLCFrame(symbol=provider_symbol, frame=trimmed, source=self.name)

        return frame

    def health(self) -> dict:
        files = sorted(p.name for p in self.directory.glob("*.csv"))
        return {
            "provider": self.name,
            "status": "ok" if files else "empty",
            "directory": str(self.directory),
            "files": len(files),
            "sample": files[:8],
        }
