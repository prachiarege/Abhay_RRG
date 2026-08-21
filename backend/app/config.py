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
    #: Source preference when a symbol has bars from more than one provider
    #: (V2-DATA-002). Comma-separated, highest priority first. A date present in an
    #: earlier source wins; later sources only fill dates the earlier ones lack.
    #:
    #: NSE is listed first because it is the exchange itself and therefore authoritative;
    #: Yahoo follows because it holds the deep history that NSE's day-file archive would
    #: take thousands of requests to reproduce.
    source_priority: str = "nse,yahoo,csv"
    #: Provider used for the routine index refresh, and the one to fall back to when it
    #: cannot serve a symbol (V2-DATA-002). Distinct from `data_provider`, which is the
    #: single-provider default used by direct calls and by the constituent fetch.
    index_provider: str = "nse"
    index_fallback_provider: str = "yahoo"
    #: How far back a routine NSE refresh reaches. The archive is one file per day, so this
    #: is a request count -- but files are cached on disk, so a daily run only downloads the
    #: new day. Wide enough to repair a multi-week provider gap without a manual backfill.
    nse_refresh_window_days: int = 45
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

    # --- chart rendering (SRS V2 Appendix A.3) ----------------------------------
    # Presentation only. None of these touch the calculation engine -- V2 7.2 is explicit
    # that smoothing is a rendering layer and must not change observations.
    tail_smooth: bool = True
    tail_interpolation: str = "catmull_rom"
    tail_line_width: float = 2.5
    tail_fade_old_points: bool = True
    tail_show_observation_dots: bool = True
    arrow_enabled: bool = True
    arrow_size: float = 13.0
    arrow_min_movement: float = 1e-4

    # --- workspace layout bounds (SRS V2 11.4) ----------------------------------
    panel_left_min: int = 220
    panel_left_default: int = 320
    panel_left_max: int = 500
    panel_bottom_min: int = 120
    panel_bottom_default: int = 250
    panel_bottom_max_percent: int = 60

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
    def source_priority_list(self) -> list[str]:
        return [p.strip() for p in self.source_priority.split(",") if p.strip()]

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
