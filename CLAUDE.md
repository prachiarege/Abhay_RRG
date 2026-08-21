# CLAUDE.md — orientation for a fresh session

Read this before touching the code. It records the things that are **expensive to
rediscover** and the mistakes already made, so they are not made again. Everything else
lives in `docs/`, which this file points at rather than duplicates.

Assume no memory of previous sessions. This file is the handover.

---

## What this is

A Relative Rotation Graph (RRG) for Indian equity market sectors, built to an SRS
(`docs/` has the analysis). Shipped two ways: a dev setup (FastAPI + Next.js as separate
processes) and a **single-user Windows desktop `.exe`** that bundles both.

- **Backend** `backend/` — FastAPI, Pandas/NumPy, SQLAlchemy (SQLite; Postgres-ready)
- **Frontend** `frontend/` — Next.js 15, TypeScript, ECharts
- **Repo** `https://github.com/prachiarege/Abhay_RRG` (HTTPS push works; Windows Credential
  Manager holds the token)

Two SRS documents exist: the original (13 Aug 2026) and a **V2 change request**
(`Indian_Sector_Rotation_Graph_V2_SRS.docx` in `~/Downloads`). V2 is partially delivered —
see "Where things stand".

---

## Commands

```bash
# backend
cd backend
.venv/Scripts/python -m pytest -q                       # 118 tests, ~25s
.venv/Scripts/python -m uvicorn app.main:app --reload   # :8000
.venv/Scripts/python -m scripts.ingest --provider nse --from 2026-07-01 --to 2026-08-21

# frontend
cd frontend
npm run dev                 # :3000
npm run test:smoothing      # 12 interpolation-guardrail tests
npx tsc --noEmit

# desktop executable  ->  backend/dist/SectorRRG/SectorRRG.exe
cd backend && .venv/Scripts/python build_exe.py          # ~4 min
```

**Never run `npm run build` while `npm run dev` is running** — both write `.next` and the
dev server starts throwing `__webpack_modules__ is not a function`. Fix: `rm -rf .next`.

---

## The five things most likely to trip you up

### 1. Aggregates hide per-series faults. This bug class has bitten three times.

Every data-quality bug in this project has been the same shape: a healthy benchmark or a
healthy *aggregate* masking broken individual series.

- A global "latest date" looked fine while 7 sectors were weeks stale.
- A **per-symbol** "latest date" *also* looked fine, because the provider resumed
  publishing without backfilling — so every series had a current newest bar and a month
  missing from the middle.
- Only **counting bars** per symbol against the best-covered symbol found it
  (`incomplete_symbols` in `services/ingestion.py`).

Before trusting any freshness or completeness check, ask what it would report if one series
had a hole in the middle.

### 2. A NaN in a rolling window suppresses months of output

This is why data gaps matter so much more than they look. `rolling(window=N,
min_periods=N)` returns NaN if *any* value in the window is NaN. So a 4-week gap kills the
gap **plus the whole warm-up chain behind it** — measured at ~22 weeks of missing RRG
output from a 4-week hole. A gap is not a cosmetic staleness issue.

### 3. Smoothing must not invent a quadrant crossing

`frontend/lib/smoothing.ts`. A spline through points either side of the 100 line naturally
bulges across it, which on an RRG asserts a quadrant visit that never happened — an
analytical claim, not a cosmetic one. Centripetal Catmull-Rom plus a boundary guard that
clamps samples straying to the wrong side of a line their own segment does not cross.
`frontend/tests/smoothing.test.mjs` pins this. Do not swap in ECharts `smooth: true`.

### 4. Providers own their identifier namespaces

`app/seed.py` → `NAMESPACED_PROVIDERS = {"nse", "dhan"}`. NSE keys on its own index names
("Nifty IT"), Dhan on numeric security ids. Handing either a Yahoo ticker makes it search
for an index literally called `^CNXIT`. Yahoo and CSV accept a generic symbol and may fall
back to the legacy `provider_symbol` column; the namespaced ones must not.

Getting this wrong once gave the CSV provider zero symbols and broke all 21 API tests.

### 5. Test the artifact, not just the dev environment

The packaged `.exe` has its **own database** at `%LOCALAPPDATA%\SectorRRG\rrg.db`, separate
from `backend/data/`. A change can work perfectly in dev and be broken on upgrade — that
exact thing happened: a migration added a column and nothing populated it, so the packaged
app resolved zero symbols for NSE and silently did nothing.

After any data-layer change, rebuild the exe and launch it against an existing database.

---

## Non-obvious design decisions (do not "simplify" these)

| Decision | Why |
|---|---|
| Smoothing defaults to **SMA, not EMA** | An EMA seed depends on where the series starts, so historical values shift as new data arrives. SMA is window-local, which makes the no-look-ahead guarantee *exact*. |
| RS-Momentum is **not de-meaned** (RS-Ratio is) | De-meaning would make "above 100" mean "rising faster than lately" rather than "rising". SRS §8 requires the latter. |
| Series are **truncated at `as_of` before** the engine runs | Not computed-then-sliced. They agree today, which is exactly why the ordering must be deliberate: the moment anyone adds a full-sample statistic, truncate-then-compute still tells the truth. |
| Weekly bars matched by **week period**, not date label | Resampling two series independently labels each bar with its *own* last trading day, so a sector missing the benchmark's Friday silently loses the whole week. |
| Layout state lives **outside `ControlState`** | The data-fetch effect is keyed on `ControlState`; putting panel sizes there would refetch the RRG on every pixel of a divider drag. |
| Requests use **`AbortController`** | Superseded requests were only ignored in JS, so the single-worker backend chewed through every one while the UI waited on the last. |
| NSE `fetch_many` is **overridden** | The archive is per-day-all-symbols — the inverse of the per-symbol contract. The base implementation re-downloads each day file once per symbol. |
| Provider fetches capped at **6 concurrent** | Latency-bound, so serial was 3× slower; but free endpoints throttle, and a fast fetch that fails is worse than a slow one that works. |
| `migrations.py` is **additive-only** | `create_all` never alters existing tables. This closes that hole for nullable columns only. **Introduce Alembic** the moment a change needs a data migration, non-null default, rename or type change. |

---

## Data sources

**NSE archive is primary** (free, no account, authoritative):
`https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` — one file per
trading day, ~161 indices, full OHLC. Needs browser-like headers. Day files cached under
`%LOCALAPPDATA%\SectorRRG\nse_archive\`.

**Yahoo is fallback**, holding 12 years of history NSE's day-file archive would need ~3,000
requests to reproduce. The two agree **to the paise** on overlapping days, which is what
makes splicing safe.

Sources merge per-date in `RRG_SOURCE_PRIORITY` order (default `nse,yahoo,csv`). The merge
is **reported, not hidden** — `/api/health` shows each provider's contribution, because
SRS V2 §6.4 forbids a series *silently* alternating between providers.

**Dhan was evaluated and rejected**: its Data API costs ₹499/month. Full evaluation
(including which auth flows can actually be automated — only TOTP) in
`docs/SRS_DEVIATIONS.md` §1.4. The adapter seam exists if intraday or live quotes are ever
wanted.

---

## Where things stand

**Delivered:** all 18 original MVP acceptance criteria, plus historical playback, rotation
detection, sector→stock drill-down, the desktop build, and V2 Phases 3–4 (resizable
workspace, smooth tails, real arrowheads).

**V2 remaining:**

- **Config UI** (YAML import/export + settings screen — the client chose "both"). *Not*
  Dhan-dependent. **V2-AC-01 and V2-AC-02 are currently unmet**: adding an index needs a
  `seed.py` edit, which is a code change. Worth doing because NSE exposes ~161 indices and
  only 23 are wired up.
- **Dhan adapter + token manager** — only if the ₹499 subscription is bought.

**Two corrections the client should make to the V2 SRS:**

1. §16 lists stock-in-sector RRG as a Phase 6 future item. It already ships, and is visible
   in the doc's own baseline screenshot.
2. §10.3 / Appendix A.2 name `DHAN_API_KEY`/`DHAN_API_SECRET` — credentials for the one
   auth flow that *cannot* be automated, so as written it cannot satisfy V2-DATA-003.

**Open client decisions:** `docs/SRS_DEVIATIONS.md` §7.

---

## Honesty commitments in this codebase

These are load-bearing product decisions, not politeness. Preserve them.

- Stale or incomplete series are **flagged in the UI**, never silently plotted as current.
- Unavailable sectors are **reported with reasons**, never quietly dropped from a result.
- Insufficient history returns **HTTP 409 with an explanation**, not a shortened tail.
- The rotation score ships with its own caveat: it is a percentile rank *within the plotted
  set*, so it is not comparable across different selections.
- Stock-level history uses **today's** index membership and is therefore **not
  survivorship-free**. `membership_as_of` is returned and displayed.
- Data is **never silently imputed**. A gap stays a gap.

---

## Documentation map

| File | Contents |
|---|---|
| `docs/SRS_DEVIATIONS.md` | **Read first.** Every departure from the SRS, the data-source evaluation, open client decisions, and assumptions taken without an answer |
| `docs/RRG_CALCULATION_SPEC.md` | **Normative.** The mathematics the SRS left as a placeholder. Bump `ENGINE_VERSION` if this changes |
| `docs/ARCHITECTURE.md` | Pipeline, module map, schema, multi-source loading, deployment, all config vars |
| `docs/API.md` | Endpoint reference with response shapes |
| `docs/UI_UX_SPEC.md` | Design rationale, including the honesty commitments above |
| `docs/DESKTOP_BUILD.md` | Packaging, what the end user needs (nothing), troubleshooting |

---

## Environment notes

- Windows, PowerShell + Git Bash. **Bash heredocs with embedded quotes fail repeatedly
  here** — write a `.py` file to the scratchpad and run it instead of fighting the quoting.
- Python 3.14, pandas 3.0 (copy-on-write semantics), Node 24, PyInstaller 6.22.
- This folder sits under **OneDrive**. Never write secrets into the project tree; they would
  sync to the cloud. User data and any credentials belong in `%LOCALAPPDATA%\SectorRRG`.
- SRS analysis deliverables live **in this repo** under `docs/`, not in the AMA-Docs folder
  used by the unrelated AMA project.
