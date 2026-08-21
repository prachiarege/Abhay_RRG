# Indian Sector Rotation Graph (RRG)

Interactive Relative Rotation Graph for Indian equity market sectors against a selectable
benchmark. Built to the SRS dated 13 August 2026.

**Stack:** FastAPI · Pandas/NumPy · SQLAlchemy (SQLite → Postgres) · Next.js 15 ·
TypeScript · ECharts

---

## Two ways to run it

**Single-user desktop (no install).** One folder, one `.exe`, nothing to install on the
target machine — no Python, no Node.js. Build it with:

```bash
cd backend && .venv/Scripts/python build_exe.py
```

Ship `backend/dist/SectorRRG/`. See [`docs/DESKTOP_BUILD.md`](docs/DESKTOP_BUILD.md).

**Development / server mode.** Backend and frontend as separate processes, below.

---

## Quick start (development)

```bash
# --- backend ---
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt          # Windows
# .venv/bin/pip install -r requirements.txt            # macOS / Linux

.venv/Scripts/python -m scripts.ingest --years 12      # first data load (~2 min)
.venv/Scripts/python -m uvicorn app.main:app --reload
```

```bash
# --- frontend, in a second terminal ---
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. API docs at <http://localhost:8000/docs>.

```bash
# --- tests ---
cd backend  && .venv/Scripts/python -m pytest -q      # 116 tests
cd frontend && npx tsc --noEmit && npm run build
```

---

## Where the data comes from

**Primary: the NSE archive.** NSE publishes one CSV per trading day containing every index
it calculates, free and with no account:

```
https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv
```

161 indices, full OHLC, straight from the exchange. Cross-checked against Yahoo on
overlapping days: identical to the paise.

**Fallback: Yahoo Finance**, which holds twelve years of history that NSE's day-file
archive would take thousands of requests to reproduce. Sources are merged in configured
priority order (`RRG_SOURCE_PRIORITY`, default `nse,yahoo,csv`) — the higher-priority
source wins each date, lower ones fill only what it lacks — and the merge is reported
rather than hidden: `/api/health` shows exactly how many bars each provider contributed.

### Why this matters (and what it fixed)

Yahoo alone is not sufficient. It stopped publishing a whole class of NSE sector indices for
a month and never backfilled the gap. The consequence was worse than a stale reading: a NaN
anywhere in a rolling window nullifies that window, so a four-week hole suppressed RRG
output for the hole *plus* the warm-up chain behind it. Seven of ten default sectors had **no
valid weekly point at all** after 17 Jul, and would not have recovered until roughly
December.

Adding NSE closed the gap, and widened the universe as a side effect: **Oil & Gas, Consumer
Durables and Healthcare** — the three SRS 2.1 sectors Yahoo never carried — plus the
**Midcap 150 and Smallcap 250** benchmarks from SRS 2.2 are now available. 17/17 sectors and
6/6 benchmarks, up from 14 and 4.

### Honest caveats

- The archive is a **published file set, not a contracted API**: no SLA, browser-like
  headers required, and NSE could restrict it. Right for a single-user local tool; a
  commercial product should hold a data licence.
- **Dhan was evaluated and not adopted.** Its Data API costs ₹499/month and its historical
  endpoints require that subscription. The adapter seam remains, and Dhan becomes worth it
  if intraday or live quotes are ever needed — see
  [`docs/SRS_DEVIATIONS.md`](docs/SRS_DEVIATIONS.md) §1 for the full evaluation, including
  which of its authentication flows can actually be automated.

---

## What is built

**Engine** — RS, RS-Ratio, RS-Momentum, quadrants, direction, rotation detection, geometric
relative returns, composite score. Every transform is finite-window and causal.

**Data** — provider abstraction (NSE archive / Yahoo / CSV), priority-ordered
multi-source merging with reported provenance, validation for duplicates, gaps,
non-positive values, implausible spikes and non-session bars, dialect-aware upsert, audit
log, scheduled post-close refresh.

**API** — RRG payload, playback timeline, sector detail, rotations, CSV/Excel export,
refresh and admin endpoints, rate limiting, optional API key.

**UI** — interactive RRG with quadrant fields, configurable tails, direction arrows, zoom,
pan, hover, click-to-select; sortable ranking table; historical playback; sector detail
drawer with trajectory chart; PNG/SVG/CSV/Excel export.

**Sector → stock drill-down** — choose one sector, multi-select its constituents, plot them
against the benchmark. 153 tickers across 14 sectors, loaded lazily on first use. An
extension beyond the SRS: see [`docs/SRS_DEVIATIONS.md`](docs/SRS_DEVIATIONS.md) §10,
including the composition-bias limitation.

### MVP acceptance criteria (SRS 47)

AC-01 … AC-18 are all met. Beyond MVP: historical playback (SRS 21) and rotation detection
(SRS 23) are also implemented.

Not built, by scope: alert delivery (SRS 24 — detection and storage exist, channels do
not), backtesting (SRS 42–43), portfolio allocation (SRS 44). The data architecture supports
all three: `rrg_values` is keyed by date/sector/parameters and the engine is a pure
function, so history can be replayed without look-ahead.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/RRG_CALCULATION_SPEC.md`](docs/RRG_CALCULATION_SPEC.md) | **Normative.** The mathematics the SRS left as a placeholder |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Pipeline, module map, DB schema, deployment, configuration |
| [`docs/API.md`](docs/API.md) | Endpoint reference with response shapes |
| [`docs/UI_UX_SPEC.md`](docs/UI_UX_SPEC.md) | Design decisions and rationale |
| [`docs/DESKTOP_BUILD.md`](docs/DESKTOP_BUILD.md) | Single-user Windows build: what the end user needs (nothing), how packaging works, troubleshooting |
| [`docs/SRS_DEVIATIONS.md`](docs/SRS_DEVIATIONS.md) | **Read this first.** Every departure from the SRS (§1–6), 6 open client decisions (§7), and the 4 build-time assumptions taken without an answer (§9) |

---

## Three things worth knowing about the implementation

### The SRS did not specify the mathematics

Sections 7 and 8 give RS-Ratio and RS-Momentum as `100 + normalized(...)` with the
normalisation method listed as a configuration parameter. That is not implementable
unambiguously, and it makes the SRS's own acceptance criteria — 52.1 (validate against a
reference dataset) and 50.2 (reproducibility) — impossible to evaluate.

`docs/RRG_CALCULATION_SPEC.md` pins it down, and the test suite validates the
implementation against an independently coded NumPy reference to 1e-8 across 900 bars.

### No look-ahead is enforced, not asserted

Historical playback recomputes from data truncated at the selected date. The test suite
asserts that the value for date `D` from full history is bit-identical to the value for `D`
from history truncated at `D`, across 40 sampled dates — and additionally that *corrupting*
every bar after `D` leaves everything at or before `D` unchanged.

This is why smoothing defaults to SMA rather than EMA: an exponential average carries a
seed that depends on where the series starts, so historical values shift slightly as new
data arrives. The engine offers EMA and warns about it.

### SRS section 11 is wrong

It labels both upper quadrants "Leading" and places Weakening top-right. Sections 4 and 12
agree with each other and are correct — Improving top-left, Leading top-right, Lagging
bottom-left, Weakening bottom-right. The implementation follows 4 and 12 throughout and
section 11 should be deleted from the SRS.

---

## Layout

```
AAR Project/
├── backend/
│   ├── app/
│   │   ├── engine/          # pure calculation — imports no I/O
│   │   ├── providers/       # data source abstraction
│   │   ├── services/        # ingestion, validation, resample, cache, orchestration
│   │   ├── api/             # routers and dependencies
│   │   ├── models.py        # SQLAlchemy schema
│   │   ├── config.py        # all settings, env-driven
│   │   └── main.py
│   ├── tests/               # 116 tests
│   ├── scripts/ingest.py    # CLI data loader
│   └── config/nse_holidays.json
├── frontend/
│   ├── app/                 # Next.js app router
│   ├── components/          # chart, controls, table, playback, detail drawer
│   └── lib/                 # typed API client, formatting, quadrant vocabulary
└── docs/
```
