"""Shared API dependencies: parameter assembly, auth, IST formatting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Query, status

from ..config import Settings, get_settings
from ..engine.params import RRGParams
from ..schemas import RRGQuery
from ..services.rrg_service import RRGRequest

# Timestamps are stored in UTC and rendered in IST at the edge (SRS 29). A fixed offset is
# correct here: India has observed UTC+05:30 with no daylight saving since 1945.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def to_ist(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(IST).strftime("%d-%b-%Y %H:%M IST")


def rrg_query(
    benchmark: str | None = Query(default=None),
    frequency: str = Query(default="weekly"),
    sectors: str | None = Query(default=None),
    level: str = Query(default="sector", description="sector | stock"),
    sector: str | None = Query(default=None, description="required when level=stock"),
    as_of: str | None = Query(default=None, description="YYYY-MM-DD; omit for latest"),
    tail: int = Query(default=10, ge=1, le=250),
    rs_period: int = Query(default=14, ge=2, le=250),
    momentum_period: int = Query(default=10, ge=2, le=250),
    smoothing_period: int = Query(default=5, ge=1, le=100),
    smoothing_method: str = Query(default="sma"),
    norm_period: int = Query(default=14, ge=2, le=250),
    scale_factor: float = Query(default=1.0, gt=0, le=25),
    clip_sigma: float = Query(default=3.0, gt=0, le=10),
    center: float = Query(default=100.0, gt=0),
    include_partial: bool = Query(default=False),
) -> RRGQuery:
    """Validate raw query parameters into an RRGQuery.

    Pydantic's own errors are re-raised as 422 with the offending field named, so a bad
    parameter produces an actionable message instead of a stack trace.
    """
    try:
        return RRGQuery(
            benchmark=benchmark,
            frequency=frequency,
            sectors=sectors,
            level=level,
            sector=sector,
            as_of=as_of,
            tail=tail,
            rs_period=rs_period,
            momentum_period=momentum_period,
            smoothing_period=smoothing_period,
            smoothing_method=smoothing_method,
            norm_period=norm_period,
            scale_factor=scale_factor,
            clip_sigma=clip_sigma,
            center=center,
            include_partial=include_partial,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc


def build_request(
    query: RRGQuery = Depends(rrg_query),
    settings: Settings = Depends(get_settings),
) -> RRGRequest:
    """Turn validated query parameters into an engine request.

    Unspecified parameters fall back to the configured defaults rather than to literals,
    so an administrator changing a default in configuration changes it for the API too
    (SRS 40).
    """
    try:
        params = RRGParams(
            rs_period=query.rs_period,
            momentum_period=query.momentum_period,
            smoothing_period=query.smoothing_period,
            smoothing_method=query.smoothing_method,
            norm_period=query.norm_period,
            scale_factor=query.scale_factor,
            clip_sigma=query.clip_sigma,
            center=query.center,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc

    tail = min(query.tail, settings.max_tail_length)

    return RRGRequest(
        benchmark=query.benchmark or settings.default_benchmark,
        frequency=query.frequency,
        sectors=query.sector_tuple(),
        level=query.level,  # type: ignore[arg-type]
        sector=query.sector,
        as_of=query.as_of,
        tail_length=tail,
        params=params,
        include_partial=query.include_partial or settings.include_partial_week,
    )


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Guard mutating endpoints when an API key is configured (SRS 39).

    When RRG_API_KEY is unset the guard is a no-op, which keeps local development
    frictionless. Setting it is the single step that locks down refresh and admin
    endpoints -- and it must be set before this is exposed beyond localhost.
    """
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-API-Key",
        )
