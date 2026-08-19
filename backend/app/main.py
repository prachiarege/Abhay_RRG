"""FastAPI application entrypoint.

    DATA SOURCES -> ingestion -> validation -> store -> RRG engine -> API -> web app

(SRS 30.) This module wires the last two boxes together and owns startup.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import BASE_DIR, get_settings
from .db import init_db, session_scope
from .engine.params import ENGINE_VERSION
from .constituents import seed_constituents
from .seed import seed_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables, seed the universe, optionally start the scheduler."""
    init_db()
    with session_scope() as session:
        seed_universe(session)
        session.commit()
        seed_constituents(session)

    scheduler = None
    if settings.auto_refresh_enabled:
        from .scheduler import start_scheduler

        scheduler = start_scheduler()

    logger.info(
        "%s ready | engine %s | provider %s | db %s",
        settings.app_name,
        ENGINE_VERSION,
        settings.data_provider,
        settings.database_url.split("://", 1)[0],
    )
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version=ENGINE_VERSION,
    description=(
        "Relative Rotation Graph analytics for Indian equity market sectors.\n\n"
        "Coordinate system used consistently throughout this API: X = RS-Ratio, "
        "Y = RS-Momentum, centred on 100. Leading is top-right, Weakening bottom-right, "
        "Lagging bottom-left, Improving top-left."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# A minimal fixed-window rate limiter (SRS 39). Per-process and in-memory, which is
# honest for a single-worker deployment; put a real limiter in the reverse proxy or
# gateway before running several workers behind a load balancer.
_hits: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return await call_next(request)

    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _hits[client]
    while window and now - window[0] > 60.0:
        window.popleft()

    if len(window) >= limit:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"rate limit exceeded ({limit}/min)"},
        )
    window.append(now)
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Log the detail, return the SRS 46 wording -- never a stack trace to the client."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Unable to retrieve sector data. Please try again later."},
    )


app.include_router(router)


def _frontend_dir() -> Path | None:
    """Locate a statically exported frontend, if one was built.

    Present in the packaged desktop build (`RRG_DESKTOP_BUILD=1 npm run build` writes
    `frontend/out`, which PyInstaller bundles). Absent in development, where Next.js serves
    the UI itself on port 3000.
    """
    from .config import bundle_root

    candidates = (
        bundle_root() / "frontend",           # inside the PyInstaller bundle
        BASE_DIR.parent / "frontend" / "out",  # a local static export
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


_FRONTEND = _frontend_dir()

if _FRONTEND is not None:
    # Mounted last so every /api route already claimed its path. `html=True` serves
    # index.html for directory requests, which is what a Next.js static export expects.
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="ui")
    logger.info("serving bundled UI from %s", _FRONTEND)
else:

    @app.get("/", tags=["meta"])
    def root() -> dict:
        """API-only landing page. Replaced by the UI when a static export is bundled."""
        return {
            "app": settings.app_name,
            "engine_version": ENGINE_VERSION,
            "docs": "/docs",
            "health": "/api/health",
            "ui": "not bundled - run the Next.js dev server on port 3000",
        }
