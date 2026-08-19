"""API routes (SRS 33, 41, 46).

Error contract: a failure that affects the whole request is a 4xx/5xx with a readable
message; a failure that affects one sector is reported inside a successful response under
`unavailable`, so the chart still renders for everything that worked (SRS 46).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_session
from ..engine.params import ENGINE_VERSION
from ..engine.quadrants import QUADRANTS
from ..models import Benchmark, PriceData, RotationEventRow, Sector
from ..schemas import RefreshRequest
from ..constituents import seed_constituents
from ..seed import UNAVAILABLE_PREFIX, seed_universe
from ..services import ingestion
from ..services.cache import get_cache
from ..services.rrg_service import (
    InsufficientHistory,
    RRGRequest,
    available_dates,
    build_rrg,
    export_rows,
    sector_detail,
)
from .deps import build_request, require_api_key, to_ist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

EXPORT_COLUMNS = (
    "date",
    "sector",
    "symbol",
    "benchmark",
    "frequency",
    "rs_ratio",
    "rs_momentum",
    "quadrant",
    "is_latest",
    "rotation_score",
    "direction",
    "rel_return_1d",
    "rel_return_1w",
    "rel_return_1m",
    "rel_return_3m",
    "rel_return_6m",
    "rel_return_1y",
    "engine_version",
    "params_fingerprint",
)


# ---------------------------------------------------------------------------- metadata


@router.get("/health", tags=["meta"])
def health(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    freshness = ingestion.data_freshness(session)
    last = ingestion.last_ingestion(session)
    finished = last.get("finished_at") if last else None
    finished_dt = datetime.fromisoformat(finished) if finished else None

    return {
        "status": "ok",
        "app": settings.app_name,
        "engine_version": ENGINE_VERSION,
        "environment": settings.environment,
        "provider": settings.data_provider,
        "database": settings.database_url.split("://", 1)[0],
        "last_updated_utc": finished,
        "last_updated_ist": to_ist(finished_dt),
        "data": freshness,
        "cache": get_cache().stats(),
        "last_ingestion": last,
    }


@router.get("/sectors", tags=["meta"])
def list_sectors(
    include_inactive: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Sector universe (SRS 33). Never hard-coded -- always read from the table."""
    query = select(Sector).order_by(Sector.sort_order)
    if not include_inactive:
        query = query.where(Sector.active.is_(True))
    return [
        {
            "symbol": s.symbol,
            "name": s.display_name,
            "short_name": s.short_name,
            "full_name": s.sector_name,
            "color": s.color,
            "is_default": s.is_default,
            "active": s.active,
            "provider_symbol": s.provider_symbol,
            "available": not s.provider_symbol.startswith(UNAVAILABLE_PREFIX),
        }
        for s in session.scalars(query)
    ]


@router.get("/benchmarks", tags=["meta"])
def list_benchmarks(
    include_inactive: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> list[dict]:
    query = select(Benchmark).order_by(Benchmark.sort_order)
    if not include_inactive:
        query = query.where(Benchmark.active.is_(True))
    return [
        {
            "symbol": b.symbol,
            "name": b.benchmark_name,
            "display_name": b.display_name,
            "is_default": b.is_default,
            "active": b.active,
            "available": not b.provider_symbol.startswith(UNAVAILABLE_PREFIX),
        }
        for b in session.scalars(query)
    ]


@router.get("/sectors/{symbol}/constituents", tags=["meta"])
def list_constituents(
    symbol: str,
    session: Session = Depends(get_session),
) -> dict:
    """The stocks making up one sector index, for the drill-down picker.

    `data_loaded` tells the client whether prices are already stored. On a first drill-down
    they will not be, and the RRG request will fetch them — which takes a few seconds and is
    worth showing a progress state for.
    """
    from sqlalchemy import func

    from ..models import Stock

    sector = session.scalar(select(Sector).where(Sector.symbol == symbol))
    if sector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown sector: {symbol}"
        )

    members = list(
        session.scalars(
            select(Stock).where(Stock.sector_symbol == symbol).order_by(Stock.sort_order)
        )
    )
    if not members:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no constituents recorded for {symbol}. "
                "Seed them with POST /api/admin/seed."
            ),
        )

    stored = {
        row[0]: row[1]
        for row in session.execute(
            select(PriceData.symbol, func.max(PriceData.date))
            .where(PriceData.symbol.in_([m.symbol for m in members]))
            .group_by(PriceData.symbol)
        ).all()
    }

    return {
        "sector": sector.symbol,
        "sector_name": sector.display_name,
        # The membership snapshot date. Index composition changes over time, so a
        # stock-level view of history built from a current snapshot carries composition
        # bias; the UI states this rather than implying survivorship-free history.
        "membership_as_of": members[0].as_of.isoformat() if members[0].as_of else None,
        "count": len(members),
        "data_loaded": sum(1 for m in members if m.symbol in stored),
        "stocks": [
            {
                "symbol": m.symbol,
                "name": m.company_name,
                "color": m.color,
                "active": m.active,
                "available": m.data_available,
                "data_loaded": m.symbol in stored,
                "latest_date": stored[m.symbol].isoformat() if m.symbol in stored else None,
            }
            for m in members
        ],
    }


@router.post("/sectors/{symbol}/constituents/refresh", tags=["admin"])
def refresh_constituents(
    symbol: str,
    force: bool = Query(default=False, description="re-fetch stocks that already have data"),
    session: Session = Depends(get_session),
) -> dict:
    """Download price history for a sector's constituents."""
    try:
        result = ingestion.refresh_sector_stocks(
            session, symbol, only_missing=not force, trigger="manual"
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    get_cache().clear("rrg|stock")
    return result.to_dict()


@router.get("/config", tags=["meta"])
def read_config(settings: Settings = Depends(get_settings)) -> dict:
    """Effective defaults, so the UI never hard-codes them either (SRS 40)."""
    return {
        "app_name": settings.app_name,
        "engine_version": ENGINE_VERSION,
        "quadrants": list(QUADRANTS),
        "provider": settings.data_provider,
        "defaults": {
            "benchmark": settings.default_benchmark,
            "frequency": settings.default_frequency,
            "tail_length": settings.default_tail_length,
            "display_history": settings.default_display_history,
            "rs_period": settings.rs_period,
            "momentum_period": settings.momentum_period,
            "smoothing_period": settings.smoothing_period,
            "smoothing_method": settings.smoothing_method,
            "norm_period": settings.norm_period,
            "scale_factor": settings.scale_factor,
            "clip_sigma": settings.clip_sigma,
            "center": settings.quadrant_center,
            "include_partial_week": settings.include_partial_week,
        },
        "limits": {
            "max_tail_length": settings.max_tail_length,
            "tail_options": [5, 10, 15, 20, 30, 40, 60],
            "frequencies": ["daily", "weekly"],
            "smoothing_methods": ["none", "sma", "ema"],
        },
        "score_weights": {
            "rs_ratio": settings.score_weight_rs_ratio,
            "rs_momentum": settings.score_weight_rs_momentum,
            "momentum_change": settings.score_weight_momentum_change,
        },
    }


# --------------------------------------------------------------------------------- rrg


@router.get("/rrg", tags=["rrg"])
def get_rrg(
    request: RRGRequest = Depends(build_request),
    session: Session = Depends(get_session),
) -> dict:
    """RRG payload for the requested benchmark, frequency, date and parameters.

    With `level=stock&sector=<symbol>` this plots that sector's constituents instead of the
    sector indices. Constituent prices are fetched on first use, so the initial drill-down
    into a sector takes several seconds while roughly 10-20 symbols are downloaded;
    afterwards it is served from the database like anything else.
    """
    if request.level == "stock" and request.sector:
        try:
            fetch = ingestion.refresh_sector_stocks(
                session, request.sector, only_missing=True, trigger="drilldown"
            )
            if fetch.rows_written:
                # New prices invalidate any cached stock-level payload for this sector.
                get_cache().clear("rrg|stock")
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        except Exception:  # noqa: BLE001
            # A fetch failure must not block the request: whatever is already stored can
            # still be plotted, and per-stock reasons are reported in `unavailable`.
            logger.exception("constituent fetch failed for %s", request.sector)

    try:
        return build_rrg(session, request)
    except InsufficientHistory as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/rrg/dates", tags=["rrg"])
def get_available_dates(
    request: RRGRequest = Depends(build_request),
    session: Session = Depends(get_session),
) -> dict:
    """Dates the playback control may select (SRS 21).

    Excludes the warm-up window, so every offered date renders a real chart.
    """
    dates = available_dates(
        session,
        request.benchmark,
        request.frequency,
        request.params,
        request.include_partial,
    )
    return {
        "benchmark": request.benchmark,
        "frequency": request.frequency,
        "warmup_bars": request.params.min_bars,
        "count": len(dates),
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "dates": dates,
    }


@router.get("/sectors/{symbol}/detail", tags=["rrg"])
def get_sector_detail(
    symbol: str,
    request: RRGRequest = Depends(build_request),
    session: Session = Depends(get_session),
) -> dict:
    try:
        return sector_detail(session, symbol, request)
    except InsufficientHistory as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/rotations", tags=["rrg"])
def get_rotations(
    limit: int = Query(default=100, ge=1, le=1000),
    signal: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Persisted rotation events, newest first (SRS 23)."""
    query = select(RotationEventRow).order_by(
        RotationEventRow.date.desc(), RotationEventRow.id.desc()
    )
    if signal:
        query = query.where(RotationEventRow.signal == signal)
    rows = session.scalars(query.limit(limit))
    return [
        {
            "date": r.date.isoformat(),
            "symbol": r.sector_symbol,
            "benchmark": r.benchmark_symbol,
            "timeframe": r.timeframe,
            "previous_quadrant": r.previous_quadrant,
            "current_quadrant": r.current_quadrant,
            "signal": r.signal,
            "rs_ratio": r.rs_ratio,
            "rs_momentum": r.rs_momentum,
        }
        for r in rows
    ]


# ------------------------------------------------------------------------------ export


@router.get("/export/rrg.csv", tags=["export"])
def export_csv(
    request: RRGRequest = Depends(build_request),
    session: Session = Depends(get_session),
) -> Response:
    """CSV export (SRS 41). Values come from the same payload the screen renders."""
    try:
        rows = export_rows(session, request)
    except InsufficientHistory as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(EXPORT_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"rrg_{request.benchmark}_{request.frequency}_{stamp}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/rrg.xlsx", tags=["export"])
def export_xlsx(
    request: RRGRequest = Depends(build_request),
    session: Session = Depends(get_session),
) -> Response:
    """Excel export (SRS 41), with a parameters sheet so a saved file stays interpretable."""
    try:
        payload = build_rrg(session, request)
        rows = export_rows(session, request)
    except InsufficientHistory as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="openpyxl is not installed; use /api/export/rrg.csv",
        ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "RRG Values"
    sheet.append(list(EXPORT_COLUMNS))
    for row in rows:
        sheet.append([row.get(column) for column in EXPORT_COLUMNS])
    sheet.freeze_panes = "A2"

    meta = workbook.create_sheet("Parameters")
    meta.append(["Field", "Value"])
    meta.append(["Benchmark", payload["benchmark_name"]])
    meta.append(["Frequency", payload["frequency"]])
    meta.append(["As of", payload["date"]])
    meta.append(["Tail length", payload["tail_length"]])
    meta.append(["Engine version", payload["engine_version"]])
    meta.append(["Parameter fingerprint", payload["params_fingerprint"]])
    meta.append(["Warm-up bars", payload["warmup_bars"]])
    for key, value in payload["params"].items():
        meta.append([key, value])
    meta.append(["Note", payload["score_note"]])
    meta.column_dimensions["A"].width = 26
    meta.column_dimensions["B"].width = 60

    stream = io.BytesIO()
    workbook.save(stream)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"rrg_{request.benchmark}_{request.frequency}_{stamp}.xlsx"
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------------------------------------------------------- admin


@router.post("/refresh", tags=["admin"], dependencies=[Depends(require_api_key)])
def refresh(
    payload: RefreshRequest | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """Manual data refresh (SRS 29). Returns a per-symbol report, not just a status."""
    payload = payload or RefreshRequest()
    symbols = None
    if payload.symbols:
        from ..seed import ingestable_symbols

        everything = ingestable_symbols(session)
        symbols = {k: v for k, v in everything.items() if k in set(payload.symbols)}
        missing = sorted(set(payload.symbols) - set(symbols))
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown or unavailable symbols: {', '.join(missing)}",
            )

    result = ingestion.refresh_prices(session, symbols=symbols, trigger="manual")
    # Prices changed, so every cached RRG payload is now potentially stale.
    cleared = get_cache().clear()
    body = result.to_dict()
    body["cache_entries_cleared"] = cleared
    return body


@router.post("/admin/seed", tags=["admin"], dependencies=[Depends(require_api_key)])
def reseed(
    overwrite: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> dict:
    result = seed_universe(session, overwrite=overwrite)
    session.commit()
    result["constituents"] = seed_constituents(session, overwrite=overwrite)
    session.commit()
    return result


@router.post("/admin/cache/clear", tags=["admin"], dependencies=[Depends(require_api_key)])
def clear_cache(prefix: str | None = Query(default=None)) -> dict:
    return {"cleared": get_cache().clear(prefix)}


@router.get("/admin/provider/health", tags=["admin"], dependencies=[Depends(require_api_key)])
def provider_health() -> dict:
    """Probe the configured provider. Useful when a refresh returns nothing."""
    from ..providers import available_providers, get_provider

    return {
        "configured": get_provider().health(),
        "available": available_providers(),
    }
