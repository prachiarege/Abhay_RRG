"""Application configuration (SRS 40).

Every operational parameter is settable from the environment or a .env file, so normal
parameter changes never require a source-code change. Defaults follow SRS 51.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]

#: True when running from a PyInstaller bundle (the packaged desktop .exe).
FROZEN = bool(getattr(sys, "frozen", False))


def data_root() -> Path:
    """Where the database and CSV drops live.

    When frozen, this MUST NOT be the application directory. PyInstaller extracts a
    one-file bundle to a temporary path that is deleted on exit, so a database written
    beside the executable would be silently discarded on every run. User data therefore
    goes to %LOCALAPPDATA%\\SectorRRG, which survives both restarts and app upgrades.
    """
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) if base else Path.home()) / "SectorRRG"
    return BASE_DIR / "data"


DATA_ROOT = data_root()


def bundle_root() -> Path:
    """Directory holding bundled read-only resources (the exported frontend, configs)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else BASE_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Both locations are read, later winning: the repo's .env for development, and one
        # in the user data directory so a packaged install can be reconfigured without
        # touching the executable.
        env_file=(str(BASE_DIR / ".env"), str(DATA_ROOT / ".env")),
        env_prefix="RRG_",
        extra="ignore",
    )

    app_name: str = "Indian Sector Rotation Graph"
    environment: str = "development"

    # SQLite by default so the app runs with zero infrastructure. Point this at
    # postgresql+psycopg://... for production; no code changes are required.
    database_url: str = f"sqlite:///{(DATA_ROOT / 'rrg.db').as_posix()}"
    sql_echo: bool = False

    # --- data provider -----------------------------------------------------------
    # yahoo | csv | nse
    data_provider: str = "yahoo"
    csv_data_dir: str = str(DATA_ROOT / "csv")
    provider_timeout_seconds: int = 30
    history_years: int = 12

    # --- engine defaults (SRS 51) ------------------------------------------------
    default_benchmark: str = "NIFTY500"
    default_frequency: str = "weekly"
    default_tail_length: int = 10
    default_display_history: str = "1y"
    rs_period: int = 14
    momentum_period: int = 10
    smoothing_period: int = 5
    smoothing_method: str = "sma"
    norm_period: int = 14
    scale_factor: float = 1.0
    clip_sigma: float = 3.0
    quadrant_center: float = 100.0
    include_partial_week: bool = False

    # --- rotation score weights (SRS 26) ----------------------------------------
    score_weight_rs_ratio: float = 0.40
    score_weight_rs_momentum: float = 0.40
    score_weight_momentum_change: float = 0.20

    # --- caching (SRS 38) --------------------------------------------------------
    cache_ttl_seconds: int = 900
    cache_max_entries: int = 512
    redis_url: str | None = None

    # --- refresh scheduling (SRS 29) --------------------------------------------
    auto_refresh_enabled: bool = False
    refresh_hour_ist: int = 18
    refresh_minute_ist: int = 30

    # --- api ---------------------------------------------------------------------
    api_key: str | None = None
    cors_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = 120
    max_tail_length: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        return DATA_ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Path(settings.csv_data_dir).mkdir(parents=True, exist_ok=True)
    return settings
