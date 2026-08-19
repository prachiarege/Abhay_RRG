"""Pydantic models for API input validation and response documentation (SRS 33, 39)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class SectorOut(BaseModel):
    symbol: str
    name: str
    short_name: str
    full_name: str
    color: str | None = None
    is_default: bool
    active: bool
    provider_symbol: str
    available: bool = Field(
        description="False when the configured provider is known not to carry this index."
    )


class BenchmarkOut(BaseModel):
    symbol: str
    name: str
    display_name: str
    is_default: bool
    active: bool
    available: bool


class TailPoint(BaseModel):
    date: str
    rs_ratio: float | None
    rs_momentum: float | None
    quadrant: str | None


class RelativeReturns(BaseModel):
    d1: float | None = Field(default=None, alias="1d")
    w1: float | None = Field(default=None, alias="1w")
    m1: float | None = Field(default=None, alias="1m")
    m3: float | None = Field(default=None, alias="3m")
    m6: float | None = Field(default=None, alias="6m")
    y1: float | None = Field(default=None, alias="1y")

    model_config = {"populate_by_name": True}


class SectorPoint(BaseModel):
    symbol: str
    name: str
    short_name: str
    full_name: str
    color: str | None
    rs_ratio: float | None
    rs_momentum: float | None
    quadrant: str | None
    previous_quadrant: str | None
    direction: str | None
    direction_label: str
    rotation_score: float | None
    date: str
    relative_returns: dict[str, float | None]
    tail: list[TailPoint]


class UnavailableSector(BaseModel):
    symbol: str
    name: str
    reason: str


class RotationOut(BaseModel):
    date: str
    symbol: str
    previous_quadrant: str
    current_quadrant: str
    signal: str
    rs_ratio: float
    rs_momentum: float


class RRGResponse(BaseModel):
    benchmark: str
    benchmark_name: str
    frequency: str
    date: str | None
    requested_as_of: str | None
    tail_length: int
    center: float
    engine_version: str
    params: dict
    params_fingerprint: str
    warmup_bars: int
    bars_available: int
    sectors: list[SectorPoint]
    unavailable: list[UnavailableSector]
    rotations: list[RotationOut]
    score_note: str


class RRGQuery(BaseModel):
    """Validated query parameters for /api/rrg (SRS 33).

    Bounds exist so that a malformed or hostile request cannot ask the server to compute
    something absurd (SRS 39, input validation).
    """

    benchmark: str | None = None
    frequency: str = "weekly"
    sectors: str | None = Field(
        default=None, description="Comma-separated symbols. Omit for the default universe."
    )
    as_of: date | None = None
    tail: int = Field(default=10, ge=1, le=250)
    rs_period: int = Field(default=14, ge=2, le=250)
    momentum_period: int = Field(default=10, ge=2, le=250)
    smoothing_period: int = Field(default=5, ge=1, le=100)
    smoothing_method: str = "sma"
    norm_period: int = Field(default=14, ge=2, le=250)
    scale_factor: float = Field(default=1.0, gt=0, le=25)
    clip_sigma: float = Field(default=3.0, gt=0, le=10)
    center: float = Field(default=100.0, gt=0)
    include_partial: bool = False

    @field_validator("frequency")
    @classmethod
    def _check_frequency(cls, value: str) -> str:
        allowed = {"daily", "weekly"}
        lowered = value.strip().lower()
        if lowered not in allowed:
            raise ValueError(f"frequency must be one of {sorted(allowed)}")
        return lowered

    @field_validator("smoothing_method")
    @classmethod
    def _check_smoothing(cls, value: str) -> str:
        allowed = {"none", "sma", "ema"}
        lowered = value.strip().lower()
        if lowered not in allowed:
            raise ValueError(f"smoothing_method must be one of {sorted(allowed)}")
        return lowered

    def sector_tuple(self) -> tuple[str, ...]:
        if not self.sectors:
            return ()
        return tuple(s.strip() for s in self.sectors.split(",") if s.strip())


class RefreshRequest(BaseModel):
    symbols: list[str] | None = None
    full_history: bool = Field(
        default=False,
        description="Re-request the provider's entire window rather than recent bars only.",
    )


class HealthResponse(BaseModel):
    status: str
    app: str
    engine_version: str
    environment: str
    provider: str
    database: str
    last_updated_utc: str | None
    last_updated_ist: str | None
    data: dict
    cache: dict
    last_ingestion: dict | None
