"""Build the Windows desktop executable.

    python build_exe.py            # full build
    python build_exe.py --skip-ui  # reuse an existing frontend export

Two stages:

1.  Export the Next.js UI to static files (`frontend/out`). This is what lets the packaged
    app serve its own UI and therefore need no Node.js on the target machine.
2.  Run PyInstaller against SectorRRG.spec, producing `dist/SectorRRG/SectorRRG.exe`.

Node.js is required to BUILD, never to RUN. The finished folder is self-contained.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parent
FRONTEND = ROOT / "frontend"
DIST = BACKEND / "dist" / "SectorRRG"


def run(command: list[str], cwd: Path, env: dict | None = None) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}\n  (in {cwd})\n")
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(command, cwd=str(cwd), env=merged, shell=False)
    if result.returncode != 0:
        raise SystemExit(f"failed ({result.returncode}): {printable}")


def npm() -> str:
    """npm is a .cmd shim on Windows and must be resolved explicitly."""
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if not found:
        raise SystemExit(
            "npm not found. Node.js is required to BUILD the executable "
            "(never to run it). Install from https://nodejs.org and retry."
        )
    return found


def build_frontend() -> None:
    print("=" * 70)
    print("Stage 1 of 2: exporting the UI to static files")
    print("=" * 70)

    if not (FRONTEND / "node_modules").is_dir():
        run([npm(), "install"], cwd=FRONTEND)

    # A stale .next from a normal dev/server build produces a confusing export; start clean.
    for stale in (FRONTEND / ".next", FRONTEND / "out"):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)

    # RRG_DESKTOP_BUILD switches next.config.mjs to output:"export" and sets the API base to
    # the empty string, so the UI makes same-origin requests to whichever port we bind.
    run([npm(), "run", "build"], cwd=FRONTEND, env={"RRG_DESKTOP_BUILD": "1"})

    index = FRONTEND / "out" / "index.html"
    if not index.is_file():
        raise SystemExit(
            f"static export missing: {index}\n"
            "Check that next.config.mjs sets output:'export' when RRG_DESKTOP_BUILD=1."
        )

    size = sum(f.stat().st_size for f in (FRONTEND / "out").rglob("*") if f.is_file())
    print(f"\n  exported UI: {size / 1_048_576:.1f} MB -> {FRONTEND / 'out'}")


def build_exe() -> None:
    print("\n" + "=" * 70)
    print("Stage 2 of 2: packaging the application")
    print("=" * 70)
    print("  This takes several minutes and writes a few hundred MB.\n")

    for stale in (BACKEND / "build", BACKEND / "dist"):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)

    run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "SectorRRG.spec"],
        cwd=BACKEND,
    )

    exe = DIST / "SectorRRG.exe"
    if not exe.is_file():
        raise SystemExit(f"expected {exe} but it was not produced")


def write_readme() -> None:
    """A plain-language note for whoever receives the folder."""
    (DIST / "READ ME FIRST.txt").write_text(
        "Indian Sector Rotation Graph\r\n"
        "============================\r\n"
        "\r\n"
        "TO START\r\n"
        "  Double-click  SectorRRG.exe\r\n"
        "\r\n"
        "  A black window opens and your browser follows a moment later.\r\n"
        "  Keep the black window open while you use the app - closing it\r\n"
        "  stops the application. Press Ctrl+C in it to shut down.\r\n"
        "\r\n"
        "FIRST RUN\r\n"
        "  The first launch downloads about 12 years of market history.\r\n"
        "  It takes roughly two minutes and needs an internet connection.\r\n"
        "  Later launches start in a few seconds.\r\n"
        "\r\n"
        "TO GET FRESH DATA\r\n"
        "  Click 'Refresh data' at the top right of the app. Do this after\r\n"
        "  market close for the current day's figures.\r\n"
        "\r\n"
        "WHAT YOU NEED INSTALLED\r\n"
        "  Nothing. Python and Node.js are already inside this folder.\r\n"
        "  You need a browser (Edge is fine) and internet for data refreshes.\r\n"
        "\r\n"
        "WHERE YOUR DATA LIVES\r\n"
        "  %LOCALAPPDATA%\\SectorRRG\r\n"
        "  Paste that into File Explorer to find it. Deleting that folder\r\n"
        "  resets the app; it will download everything again next launch.\r\n"
        "\r\n"
        "IF WINDOWS WARNS ABOUT THE APP\r\n"
        "  The executable is not code-signed, so SmartScreen may show\r\n"
        "  'Windows protected your PC'. Choose More info > Run anyway.\r\n"
        "\r\n"
        "IMPORTANT LIMITATION\r\n"
        "  Market data comes from a free public source that is unreliable\r\n"
        "  for some sector indices - occasionally weeks out of date. The app\r\n"
        "  marks any stale sector in the table and in a banner above the\r\n"
        "  chart. Trust those warnings.\r\n"
        "\r\n"
        "  Move the whole folder wherever you like; keep it together.\r\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the desktop executable")
    parser.add_argument("--skip-ui", action="store_true", help="reuse frontend/out")
    args = parser.parse_args()

    started = time.monotonic()

    if args.skip_ui:
        if not (FRONTEND / "out" / "index.html").is_file():
            raise SystemExit("--skip-ui given but frontend/out/index.html does not exist")
        print("Stage 1 skipped: reusing the existing UI export.")
    else:
        build_frontend()

    build_exe()
    write_readme()

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    minutes, seconds = divmod(int(time.monotonic() - started), 60)

    print("\n" + "=" * 70)
    print("  Build complete")
    print("=" * 70)
    print(f"  Executable : {DIST / 'SectorRRG.exe'}")
    print(f"  Folder size: {total / 1_048_576:.0f} MB")
    print(f"  Took       : {minutes}m {seconds}s")
    print("\n  Ship the whole SectorRRG folder. Nothing needs installing on the")
    print("  target machine - no Python, no Node.js.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
