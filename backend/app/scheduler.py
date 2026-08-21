"""Scheduled data refresh (SRS 29).

APScheduler rather than Celery: the workload is one job a day, so a broker plus worker
processes would be infrastructure without a purpose. If the job set ever grows into
something that needs retries, fan-out or a separate worker fleet, Celery becomes the
right answer -- `refresh_job` is written to be callable from either.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_settings
from .db import session_scope
from .engine.params import RRGParams
from .services.cache import get_cache
from .services.ingestion import needs_deep_history, refresh_indices
from .services.rrg_service import persist_rotations

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def refresh_job(trigger: str = "scheduled") -> dict:
    """Fetch prices, rescan rotations, drop stale cache entries.

    Runs after market close so it sees a complete session. Exceptions are caught and
    logged rather than raised: a failed refresh must not kill the scheduler thread and
    take every future refresh with it.
    """
    settings = get_settings()
    summary: dict = {"trigger": trigger}
    try:
        with session_scope() as session:
            # NSE for the recent window, Yahoo for anything it cannot serve, plus deep
            # history if the store is too thin to warm the engine up.
            result = refresh_indices(
                session, trigger=trigger, deep=needs_deep_history(session)
            )
            summary["ingestion"] = result.get("status")
            summary["rows_written"] = result.get("rows_written", 0)
            summary["steps"] = [
                f"{step['role']}/{step['provider']}: "
                f"{step.get('succeeded', step.get('error'))}"
                for step in result.get("steps", [])
            ]

            for frequency in ("daily", "weekly"):
                try:
                    summary[f"rotations_{frequency}"] = persist_rotations(
                        session,
                        benchmark=settings.default_benchmark,
                        frequency=frequency,
                        params=RRGParams(
                            rs_period=settings.rs_period,
                            momentum_period=settings.momentum_period,
                            smoothing_period=settings.smoothing_period,
                            smoothing_method=settings.smoothing_method,
                            norm_period=settings.norm_period,
                            scale_factor=settings.scale_factor,
                            clip_sigma=settings.clip_sigma,
                            center=settings.quadrant_center,
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("rotation scan failed for %s", frequency)

        summary["cache_cleared"] = get_cache().clear()
        logger.info("refresh job complete: %s", summary)
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh job failed")
        summary["error"] = str(exc)
    return summary


def start_scheduler() -> BackgroundScheduler:
    """Start the daily refresh. Cron is expressed in IST, the market's own timezone."""
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(
        refresh_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=settings.refresh_hour_ist,
            minute=settings.refresh_minute_ist,
            timezone=IST,
        ),
        id="daily_refresh",
        name="Daily post-close data refresh",
        replace_existing=True,
        # If the process was down at the scheduled moment, run once on restart rather
        # than firing every missed occurrence.
        coalesce=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "scheduler started: weekdays at %02d:%02d IST",
        settings.refresh_hour_ist,
        settings.refresh_minute_ist,
    )
    return scheduler
