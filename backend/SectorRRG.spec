# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the single-user Windows desktop build.

Produces a ONE-FOLDER bundle (`dist/SectorRRG/SectorRRG.exe`) rather than a one-file
executable, deliberately:

*   One-file re-extracts the whole bundle (pandas, numpy, and the rest — several hundred MB)
    into a temp directory on EVERY launch. Startup goes from a few seconds to 20-40, and
    antivirus scanners re-inspect the payload each time.
*   One-folder starts fast, and a corrupt file is visible rather than mysterious.

Build with `python build_exe.py`, which exports the frontend first and then invokes this.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Packages whose data files, DLLs or dynamically-imported submodules PyInstaller cannot
# discover by static analysis alone.
datas = []
binaries = []
hiddenimports = []

for package in (
    "yfinance",      # pulls curl_cffi, peewee, protobuf, bs4, lxml
    "curl_cffi",     # ships compiled certs and DLLs
    "apscheduler",   # resolves triggers and executors through entry points
    "openpyxl",
    "pydantic",
    "pydantic_settings",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# uvicorn selects its event loop and protocol implementations at runtime by string, so none
# of these are reachable by static analysis.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "encodings.idna",
]

# The application package itself, so nothing imported inside a function body is missed.
hiddenimports += collect_submodules("app")

# Read-only resources.
datas += [
    # The statically exported Next.js UI, served by FastAPI at "/".
    ("../frontend/out", "frontend"),
    # Holiday table (ships empty; the trading calendar is derived from benchmark data).
    ("config/nse_holidays.json", "config"),
]

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trimming these keeps the bundle a few hundred MB smaller. None are used at runtime:
    # plotting, notebooks, and test frameworks have no place in a packaged app.
    excludes=[
        "matplotlib",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "_pytest",
        "sphinx",
        "setuptools._distutils",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SectorRRG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX compression is a common false-positive trigger for antivirus
    console=True,  # the window carries the URL and the stop instruction
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SectorRRG",
)
