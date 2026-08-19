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
cd backend  && .venv/Scripts/python -m pytest -q      # 102 tests
cd frontend && npx tsc --noEmit && npm run build
```

---

## Read this before trusting the numbers

**The default data provider is not production-grade.** Yahoo Finance is wired up because it
works with no key and no contract, which is what a development build needs. Two problems
make it unsuitable for anything client-facing:

1. **Licensing** — Yahoo's terms forbid redistribution and commercial use.
2. **Coverage** — 3 of the 17 SRS sectors are absent entirely, and Yahoo stopped updating a
   whole class of NSE sector symbols for roughly a month in Jul–Aug 2026. At the time of
   writing that left **7 of the 10 default sectors four weeks stale**.

The application detects and displays this — stale sectors are flagged in the table and
named in a banner — so nobody is misled. But a sector-rotation tool needs current sectors.
Moving to a licensed NSE feed, or scheduling NSE archives into the CSV provider, is a config
change plus one class. See [`docs/SRS_DEVIATIONS.md`](docs/SRS_DEVIATIONS.md) §1.

---

## What is built

**Engine** — RS, RS-Ratio, RS-Momentum, quadrants, direction, rotation detection, geometric
relative returns, composite score. Every transform is finite-window and causal.

**Data** — provider abstraction (Yahoo / CSV / NSE stub), validation for duplicates, gaps,
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
│   ├── tests/               # 102 tests
│   ├── scripts/ingest.py    # CLI data loader
│   └── config/nse_holidays.json
├── frontend/
│   ├── app/                 # Next.js app router
│   ├── components/          # chart, controls, table, playback, detail drawer
│   └── lib/                 # typed API client, formatting, quadrant vocabulary
└── docs/
```
