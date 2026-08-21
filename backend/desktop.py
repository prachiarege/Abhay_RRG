"""Desktop launcher — the entry point for the packaged Windows executable.

Responsibilities, in order:

1.  Create the database and seed the sector/benchmark universe on first run.
2.  If there is no price data yet, fetch it (needs internet, takes a couple of minutes).
3.  Bind a local HTTP server, preferring a stable port so the browser bookmark keeps working.
4.  Open the default browser at the app.
5.  Stay running until the user closes the window or presses Ctrl+C.

Everything is bound to 127.0.0.1 only. Nothing is reachable from the network, which is the
right posture for a single-user local tool and is why the build ships without
authentication.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path

# When frozen, PyInstaller has already put the bundle on sys.path. When run from source,
# make sure the backend directory is importable regardless of the working directory.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

PREFERRED_PORT = 8765
PORT_SEARCH_LIMIT = 20
HOST = "127.0.0.1"

logger = logging.getLogger("desktop")


def find_port() -> int:
    """First free port at or after PREFERRED_PORT.

    A stable port matters more than it looks: the user will bookmark the URL, so drifting to
    a random port every launch would break that bookmark. Only a genuine collision moves it.
    """
    for offset in range(PORT_SEARCH_LIMIT):
        candidate = PREFERRED_PORT + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, candidate))
                return candidate
            except OSError:
                continue
    raise RuntimeError(
        f"no free port between {PREFERRED_PORT} and {PREFERRED_PORT + PORT_SEARCH_LIMIT}"
    )


def already_running() -> int | None:
    """Detect an instance already serving, so a second launch focuses it instead of failing."""
    import json
    import urllib.request

    for offset in range(PORT_SEARCH_LIMIT):
        port = PREFERRED_PORT + offset
        try:
            with urllib.request.urlopen(
                f"http://{HOST}:{port}/api/health", timeout=1.5
            ) as response:
                payload = json.load(response)
            if payload.get("engine_version"):
                return port
        except Exception:
            continue
    return None


def banner(lines: list[str]) -> None:
    width = max(len(line) for line in lines) + 4
    print("+" + "-" * width + "+")
    for line in lines:
        print("|  " + line.ljust(width - 4) + "  |")
    print("+" + "-" * width + "+")
    sys.stdout.flush()


def ensure_data() -> tuple[bool, str]:
    """Prepare the database and load prices if empty.

    Returns (ok, message). A failure here is not fatal to startup: the app still opens and
    explains itself, because a data-fetch problem is usually transient (no internet yet) and
    the user can retry with the Refresh button rather than being locked out.
    """
    from sqlalchemy import func, select

    from app.db import init_db, session_scope
    from app.models import PriceData
    from app.constituents import seed_constituents
    from app.seed import seed_universe

    init_db()

    with session_scope() as session:
        seed_universe(session)
        session.commit()
        seed_constituents(session)
        session.commit()
        rows = session.scalar(select(func.count()).select_from(PriceData)) or 0

    if rows > 0:
        with session_scope() as session:
            latest = session.scalar(select(func.max(PriceData.date)))

        # Top up if the store has fallen behind. Two cases make this worth doing at launch
        # rather than waiting for the user to press Refresh: a desktop app is often opened
        # days apart, and an upgrade can leave correct-looking but stale data (an index the
        # previous version had no provider for). The archive's day files are cached, so a
        # same-day relaunch downloads nothing.
        #
        # Three days of slack absorbs a weekend without pointless work on a Monday morning.
        behind = latest is None or (date.today() - latest).days > 3
        if not behind:
            return True, f"{rows:,} price rows on file, latest {latest}"

        print("  Topping up market data...")
        from app.services.ingestion import refresh_indices

        try:
            with session_scope() as session:
                result = refresh_indices(session, trigger="startup", deep=False)
            with session_scope() as session:
                latest = session.scalar(select(func.max(PriceData.date)))
            added = result.get("rows_written", 0)
            if result.get("status") == "success":
                return True, f"{rows + added:,} price rows on file, latest {latest}"
            # A failed top-up is not fatal: the stored history is still usable and the app
            # flags anything stale on the chart itself.
            return True, (
                f"{rows:,} price rows on file, latest {latest} "
                "(top-up failed; use Refresh data when back online)"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup top-up failed: %s", exc)
            return True, (
                f"{rows:,} price rows on file, latest {latest} (top-up failed)"
            )

    banner(
        [
            "First run: downloading market history.",
            "This takes about two minutes and needs internet.",
            "It only happens once.",
        ]
    )

    from app.services.ingestion import refresh_indices

    try:
        with session_scope() as session:
            # deep=True: twelve years from the provider that returns it in one request per
            # symbol, then a recent window from the exchange archive layered on top.
            result = refresh_indices(session, trigger="first-run", deep=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("first-run data load failed")
        return False, f"data download failed: {exc}"

    if result.get("status") != "success":
        return False, "no data could be downloaded. Check the internet connection."

    rows = result.get("rows_written", 0)
    parts = [
        f"{step['provider']} {step.get('succeeded', 0)}/{step.get('requested', 0)}"
        for step in result.get("steps", [])
        if "requested" in step
    ]
    return True, f"downloaded {rows:,} rows ({', '.join(parts)})"


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    print()
    banner(["Indian Sector Rotation Graph", "Starting up..."])
    print()

    existing = already_running()
    if existing is not None:
        url = f"http://{HOST}:{existing}"
        print(f"  Already running at {url} - opening it.")
        webbrowser.open(url)
        return 0

    from app.config import DATA_ROOT, get_settings

    settings = get_settings()
    print(f"  Data folder : {DATA_ROOT}")
    print(f"  Provider    : {settings.data_provider}")
    print()

    ok, message = ensure_data()
    print(f"  {'Data' if ok else 'WARNING'}        : {message}")
    print()

    port = find_port()
    url = f"http://{HOST}:{port}"

    import uvicorn

    from app.main import app

    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    thread.start()

    # Wait for the socket to accept before opening the browser, so the user never sees a
    # connection-refused page on a cold start.
    deadline = time.monotonic() + 45
    ready = False
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            ready = True
            break
        if not thread.is_alive():
            break
        time.sleep(0.2)

    if not ready:
        print("  ERROR: the server did not start. See messages above.")
        input("\n  Press Enter to close...")
        return 1

    banner(
        [
            "Sector Rotation Graph is running.",
            "",
            f"Open:  {url}",
            "",
            "Keep this window open while using the app.",
            "Press Ctrl+C here to stop it.",
        ]
    )
    print()

    webbrowser.open(url)

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        server.should_exit = True
        thread.join(timeout=10)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        # A packaged app that vanishes on error is untriageable. Keep the window open with
        # the traceback visible so the user can report what happened.
        import traceback

        print("\n  Unexpected error:\n")
        traceback.print_exc()
        input("\n  Press Enter to close...")
        raise SystemExit(1)
