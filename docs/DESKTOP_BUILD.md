# Desktop build — single-user Windows install

For one person running the app locally on their own laptop. This deployment is
**127.0.0.1-only**: nothing is reachable from the network, which is why it ships without
authentication.

---

## 1. What the end user must install

**Nothing.**

Python, Node.js, the database, and every library are inside the delivered folder. The user
needs only:

| Requirement | Why | Already on Windows? |
|---|---|---|
| Windows 10 or 11, 64-bit | The build is `win-amd64` | — |
| A web browser | The UI is a local web page | Yes, Edge |
| Internet connection | Only for downloading market data | — |
| ~1.5 GB free disk | Application folder plus data | — |

No admin rights are required. No installer runs. No registry keys are written.

### What is deliberately *not* required

- **No Python.** The interpreter is bundled.
- **No Node.js.** The UI is compiled to static files that the bundled server serves itself.
  This is the whole reason a single executable is possible — see §4.
- **No Postgres, no Redis, no Docker.** SQLite and an in-process cache, which for one user
  on one machine are the correct choices rather than compromises.

---

## 2. Running it

1. Copy the whole **`SectorRRG`** folder anywhere — Desktop, Documents, a USB stick. Keep
   the folder intact; the `.exe` needs its siblings.
2. Double-click **`SectorRRG.exe`**.
3. A console window opens, then the browser follows at `http://127.0.0.1:8765`.
4. **Keep the console window open** while using the app. Closing it stops the server.
   Ctrl+C in that window shuts down cleanly.

**First launch downloads ~12 years of history** — about two minutes, needs internet. It
happens once. Later launches take a few seconds.

Launching a second time while it is already running detects the existing instance and just
reopens the browser tab, rather than failing on a port collision.

### Suggested shortcut

Right-click `SectorRRG.exe` → *Show more options* → *Send to* → *Desktop (create shortcut)*.

---

## 3. Where data lives

```
%LOCALAPPDATA%\SectorRRG
    rrg.db              SQLite database — prices, RRG values, rotation events, audit log
    .env                optional settings override (see ARCHITECTURE.md §6)
    nse_holidays.json   optional holiday list, overrides the bundled one
    csv\                drop CSV files here if using the csv provider
```

Paste `%LOCALAPPDATA%\SectorRRG` into File Explorer's address bar to open it.

**This is outside the application folder on purpose.** A one-file PyInstaller bundle unpacks
to a temporary directory that is deleted on exit, so a database written beside the
executable would be silently discarded on every run. It also means the app folder can be
replaced with a new build without losing history.

To reset completely: quit the app and delete that folder. The next launch re-downloads.

To back up: quit the app and copy `rrg.db`.

---

## 4. How it is packaged

```
  frontend/  ──[next build, output:"export"]──►  frontend/out/   (static HTML/JS/CSS)
                                                      │
                                                      ▼  bundled as a data directory
  backend/desktop.py ──[PyInstaller]──►  dist/SectorRRG/SectorRRG.exe
                                          + Python runtime
                                          + pandas / numpy / FastAPI / uvicorn
                                          + the exported UI
```

At runtime `app/main.py` locates the bundled export and mounts it at `/` via `StaticFiles`,
after the `/api` routes have claimed their paths. The frontend is built with
`NEXT_PUBLIC_API_BASE=""`, so it issues **same-origin relative** requests (`/api/rrg`) to
whatever port the process bound. One origin, one process, no CORS, no Node.

Two consequences worth knowing:

- The UI is fully static, so there is no server-side rendering. Fine here: every figure on
  the screen already came from the API at runtime.
- The port is chosen at startup (8765, or the next free one). Because requests are relative,
  the UI does not care which port it got.

### Why one folder rather than one file

`--onedir`, not `--onefile`, and deliberately:

- One-file re-extracts several hundred MB into `%TEMP%` on **every** launch. Startup goes
  from a few seconds to 20–40, and antivirus rescans the payload each time.
- One-folder starts fast, and a damaged file is visible rather than mysterious.

If a literal single file is required despite the cost, change `SectorRRG.spec` to use
`EXE(..., a.binaries, a.datas, ...)` with no `COLLECT` step. Not recommended.

---

## 5. Rebuilding

Only the **build machine** needs a toolchain:

| Tool | Version used | Purpose |
|---|---|---|
| Python | 3.14.4 | backend + PyInstaller |
| Node.js | 24.15 (npm 11.12) | compiles the UI to static files |
| PyInstaller | 6.22.2 | installed into the backend venv |

```bash
cd backend
.venv/Scripts/pip install pyinstaller
.venv/Scripts/python build_exe.py
```

`--skip-ui` reuses an existing `frontend/out` export when only backend code changed.

Output: `backend/dist/SectorRRG/`, containing the executable and a plain-language
`READ ME FIRST.txt`. Zip that folder to deliver it.

---

## 6. Things the user should be told

### SmartScreen will probably warn

The executable is not code-signed, so Windows may show *"Windows protected your PC"*. The
user chooses **More info → Run anyway**. Signing requires a code-signing certificate
(a paid annual purchase); worth it only if this is distributed more widely.

### Antivirus false positives

PyInstaller bundles are a known false-positive source. UPX compression — the biggest
trigger — is disabled in the spec for exactly this reason. If a scanner still objects, an
exclusion for the folder is the usual remedy.

### The data limitation still applies

The bundled provider is the free public feed, which is unreliable for several NSE sector
indices — at the time of building, 7 of the 10 default sectors were four weeks stale. The
app flags every stale sector in the table and in a banner. **Those warnings are the app
working correctly, not a bug.** See `SRS_DEVIATIONS.md` §1.

For dependable data, put a licensed feed behind the same provider interface, or drop NSE
archive CSVs into `%LOCALAPPDATA%\SectorRRG\csv\` and set `RRG_DATA_PROVIDER=csv` in
`%LOCALAPPDATA%\SectorRRG\.env`.

### Refreshing

The **Refresh data** button, top right. Run it after market close for the current session.
The bundled build does not enable the automatic scheduler, since a desktop app is not
usually running at 18:30 — set `RRG_AUTO_REFRESH_ENABLED=true` in the `.env` above if the
laptop is typically on then.

---

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Console flashes and vanishes | An early crash. Run from a terminal to see the traceback — the launcher keeps the window open on error, so a *flash* implies the executable itself failed to start (usually antivirus quarantine). |
| Browser shows "can't connect" | Server still starting. The launcher waits for the socket before opening the browser, so this points to the port being taken by something else — the console prints the port it actually bound. |
| Blank white page | UI assets failed to load. Check the console window for 404s on `/_next/...`; indicates an incomplete build. |
| "First run" downloads nothing | No internet, or the provider is blocked. The app still opens; use Refresh once connectivity is back. |
| Every sector shows as stale | Provider-side gap, not a local fault — see §6. |
| Numbers differ from a previous version | Check the engine version and parameter fingerprint in the Excel export's Parameters sheet. Different fingerprints are not comparable. |
