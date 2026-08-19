"""Provider registry.

    DataProvider
        |-- YahooProvider   (live default; see licensing note in yahoo.py)
        |-- CSVProvider     (deterministic / offline / licensed-file drop)
        `-- NSEProvider     (seam for a licensed feed; stub today)
"""

from __future__ import annotations

from .base import DataProvider, OHLCFrame, ProviderError, normalise_frame
from .csv_provider import CSVProvider
from .nse import NSEProvider
from .yahoo import YahooProvider

__all__ = [
    "DataProvider",
    "OHLCFrame",
    "ProviderError",
    "normalise_frame",
    "CSVProvider",
    "NSEProvider",
    "YahooProvider",
    "get_provider",
    "available_providers",
]

_REGISTRY = {
    "yahoo": YahooProvider,
    "csv": CSVProvider,
    "nse": NSEProvider,
}


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str | None = None) -> DataProvider:
    """Build the configured provider. Name defaults to RRG_DATA_PROVIDER."""
    from ..config import get_settings

    settings = get_settings()
    key = (name or settings.data_provider).strip().lower()
    if key not in _REGISTRY:
        raise ValueError(
            f"unknown data provider {key!r}; available: {', '.join(available_providers())}"
        )
    if key == "csv":
        return CSVProvider(settings.csv_data_dir)
    if key == "yahoo":
        return YahooProvider(
            history_years=settings.history_years,
            timeout=settings.provider_timeout_seconds,
        )
    return NSEProvider(timeout=settings.provider_timeout_seconds)
