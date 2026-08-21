# Architecture, Schema, Deployment and Configuration

Covers the system architecture document, database schema, deployment guide and
configuration guide from SRS 53.

---

## 1. Pipeline

```
     Market data providers  (NSE archive / Yahoo / CSV / licensed feed)
                     │
                     ▼
        ┌────────────────────────┐
        │ Ingestion              │  app/services/ingestion.py
        │ per-symbol isolation   │  one bad sector cannot fail a run
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ Validation             │  app/services/validation.py
        │ report, never impute   │  gaps/spikes/duplicates logged
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ Historical store       │  price_data  (SQLite / Postgres)
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ Resample + align       │  app/services/resample.py
        │ benchmark = calendar   │  weekly matched by week period
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ RRG engine  v1.0.0     │  app/engine/  — pure, no I/O
        │ causal, finite-window  │  see RRG_CALCULATION_SPEC.md
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ Orchestration + cache  │  app/services/rrg_service.py
        │ truncate-then-compute  │  TTL cache keyed on all inputs
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ API  (FastAPI)         │  app/api/routes.py
        └───────────┬────────────┘
                    ▼
        ┌────────────────────────┐
        │ Web app  (Next.js)     │  frontend/
        └────────────────────────┘
```

### The one structural rule

**The engine imports nothing from providers, models, or the database.** It receives pandas
Series and returns a DataFrame. This is what makes SRS 50.4 (data-provider independence)
real rather than aspirational: swapping vendors touches one class in `app/providers/` and
no line of mathematics.

---

## 2. Backend module map

| Module | Responsibility |
|---|---|
| `app/engine/params.py` | `RRGParams`, `ENGINE_VERSION`, warm-up arithmetic, fingerprinting |
| `app/engine/rrg_engine.py` | RS, RS-Ratio, RS-Momentum — the normative implementation |
| `app/engine/quadrants.py` | Classification, direction bucketing, rotation polarity |
| `app/engine/rotation.py` | Quadrant-transition and centre-crossing detection |
| `app/engine/stats.py` | Geometric relative returns, composite rotation score |
| `app/providers/` | `DataProvider` ABC + NSE archive / Yahoo / CSV implementations |
| `app/services/ingestion.py` | Fetch, validate, upsert, audit-log; priority-ordered multi-source price loading |
| `app/services/validation.py` | SRS 27 data-quality checks |
| `app/services/resample.py` | Daily/weekly conversion, cross-series weekly alignment |
| `app/services/calendar.py` | Trading-session logic and holiday warnings |
| `app/services/cache.py` | TTL/LRU cache behind a swappable interface |
| `app/services/rrg_service.py` | Request → payload orchestration, playback, export rows |
| `app/api/` | Routers, dependency wiring, parameter validation, auth |
| `app/scheduler.py` | Daily post-close refresh (APScheduler) |
| `app/seed.py` | Initial sector/benchmark universe, per-provider identifier maps |
| `app/migrations.py` | Additive-only column migrations (see below) |

---

## 3. Database schema

Postgres-compatible throughout: no SQLite-only types, explicit string lengths.

### `sectors` / `benchmarks`

Universe definition. **Never hard-coded in application logic** (SRS 2.1). Beyond the SRS
fields, each row carries `provider_symbol` (the vendor's ticker, so the canonical symbol is
vendor-independent), `short_name` (chart labels), `color`, `is_default` (the curated
on-screen set) and `sort_order`.

### `price_data`

```
PRIMARY KEY (symbol, date, source)
INDEX ix_price_symbol_date (symbol, date)
INDEX ix_price_date (date)
```

Two deliberate departures from SRS 32:

1. **A real composite primary key.** SRS 27 requires duplicate-date detection; a uniqueness
   constraint provides it at the storage layer rather than hoping application code
   remembers.
2. **A `source` column.** SRS 5.4 mandates multiple providers but the suggested schema had
   nowhere to record which one supplied a row, making vendor disagreements undebuggable.
   It is also what makes the priority-ordered merge below auditable: every bar records who
   supplied it, so a spliced series can be taken apart again.

`adjusted_close` is retained for when the universe extends beyond indices; it is
meaningless for an index.

### `rrg_values`

```
PRIMARY KEY (date, sector_symbol, benchmark_symbol, timeframe,
             params_fingerprint)
INDEX ix_rrg_lookup (benchmark_symbol, timeframe, params_fingerprint, date)
```

`params_fingerprint` and `engine_version` are the third departure from SRS 32. The SRS
exposes `rs_period`, `momentum_period` and `smoothing` as user controls (13.1) while also
requiring precomputation (37) and versioned calculations (50.3). Without these columns,
precomputed rows from different parameter sets are indistinguishable.

This table is a **cache, not a source of truth** — safe to drop and rebuild from
`price_data` at any time.

### `rotation_events`, `ingestion_log`, `app_config`

Rotation transitions (unique per date/sector/benchmark/timeframe/params, so rescanning an
overlapping window is idempotent); refresh audit trail (SRS 45); admin-editable key/value
overrides (SRS 40).

### Migrations

`Base.metadata.create_all` creates missing tables but **never alters an existing one**, so an
installed database silently keeps the old shape after a model change. `app/migrations.py`
closes that hole for the only change made so far — adding a nullable column — and is
deliberately limited to exactly that: additive, nullable, idempotent, no data rewrites.

**Alembic is still the right answer**, and the boundary is explicit: the moment a change
needs a data migration, a non-null default, a rename or a type change, stop extending that
file and introduce Alembic.

### Multi-source price loading

A symbol can hold bars from several providers. `load_close_series` merges them in
`RRG_SOURCE_PRIORITY` order (default `nse,yahoo,csv`): the highest-priority source wins each
date, lower ones fill only the dates it lacks, and an unlisted source is still used after the
listed ones rather than ignored.

This exists because the deep history and the current tail can legitimately come from
different places — Yahoo holds twelve years, NSE has the days Yahoo dropped. SRS V2 6.4
forbids a series *silently* alternating between providers, so the merge is reported:
`source_breakdown` gives each provider's actual contribution and `/api/health` exposes it.

Pass `source=` to pin a series to one provider exactly, which is what reproducibility work
should do.

---

## 4. Caching

In-process TTL + LRU cache (`TTLCache`) behind a three-method interface. Keys include every
input that affects the result: benchmark, frequency, sector set, `as_of`, tail length,
partial-week flag and the parameter fingerprint.

**Honest limitation:** it is per-process, so it buys nothing once the API runs multiple
workers. That is the point at which Redis should replace it — set `RRG_REDIS_URL` and
implement the same interface. No call sites change.

### Precompute strategy

SRS 37 asks for precomputed values, but SRS 13.1 lets users move the parameter sliders, and
the cross-product of benchmarks × frequencies × parameter sets is unbounded. The workable
resolution:

- Precompute and persist the **default** parameter sets (that is what `rrg_values` and
  `persist_rotations` are for).
- Compute on demand and cache for custom parameters.
- Measure the `< 1 s` API target against cached default requests only.

---

## 5. Running it

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # macOS / Linux

.venv/Scripts/python -m scripts.ingest --years 12  # first data load
.venv/Scripts/python -m uvicorn app.main:app --reload
```

API on `http://localhost:8000`, interactive docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App on `http://localhost:3000`.

### Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npx tsc --noEmit && npm run build
```

---

## 6. Configuration

Every operational parameter is settable from the environment or `backend/.env`, prefixed
`RRG_`. No source change is needed for normal parameter changes (SRS 40). See
`backend/.env.example`; defaults live in `app/config.py` and are exposed at `/api/config`
so the UI never hard-codes them either.

| Variable | Default | Notes |
|---|---|---|
| `RRG_DATA_PROVIDER` | `yahoo` | provider used for *fetching*: `nse` \| `yahoo` \| `csv` |
| `RRG_SOURCE_PRIORITY` | `nse,yahoo,csv` | precedence when *reading* stored bars from several sources |
| `RRG_CSV_DATA_DIR` | `backend/data/csv` | one `<PROVIDER_SYMBOL>.csv` per series |
| `RRG_HISTORY_YEARS` | 12 | initial fetch window |
| `RRG_DATABASE_URL` | SQLite in `backend/data/` | `postgresql+psycopg://…` for production |
| `RRG_DEFAULT_BENCHMARK` | `NIFTY500` | |
| `RRG_DEFAULT_FREQUENCY` | `weekly` | |
| `RRG_DEFAULT_TAIL_LENGTH` | 10 | |
| `RRG_RS_PERIOD` | 14 | |
| `RRG_MOMENTUM_PERIOD` | 10 | |
| `RRG_SMOOTHING_PERIOD` | 5 | |
| `RRG_SMOOTHING_METHOD` | `sma` | `ema` breaks exact historical reproducibility |
| `RRG_QUADRANT_CENTER` | 100.0 | |
| `RRG_INCLUDE_PARTIAL_WEEK` | false | |
| `RRG_CACHE_TTL_SECONDS` | 900 | |
| `RRG_AUTO_REFRESH_ENABLED` | false | enable in deployment |
| `RRG_REFRESH_HOUR_IST` / `_MINUTE_IST` | 18 / 30 | weekdays, post-close |
| `RRG_API_KEY` | unset | when set, guards refresh + admin endpoints |
| `RRG_CORS_ORIGINS` | `http://localhost:3000` | comma-separated |
| `RRG_RATE_LIMIT_PER_MINUTE` | 120 | 0 disables |
| `RRG_MAX_TAIL_LENGTH` | 60 | server-side ceiling |

Frontend: `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`).

---

## 7. Production checklist

Not yet done — this build targets a working local system.

1. **Replace the data provider.** Yahoo is dev-only; see `SRS_DEVIATIONS.md` §1. This is
   the single highest-priority item.
2. `RRG_DATABASE_URL` → Postgres; introduce Alembic.
3. Set `RRG_API_KEY`; put TLS and a real rate limiter in the reverse proxy (the in-process
   limiter is per-worker and advisory).
4. `RRG_AUTO_REFRESH_ENABLED=true`; confirm the host clock and the IST cron interact as
   expected.
5. Redis for cache if running more than one worker.
6. Decide the authentication model — SRS 39 leaves accounts optional while SRS 24 (alerts)
   and 40 (admin config) both need identity. Unresolved.
7. Ship logs somewhere durable; `ingestion_log` covers refreshes but not API traffic.

---

## 8. Deliberate omissions

- **Alembic** — `create_all` is sufficient until the schema moves.
- **Celery/Redis broker** — one job a day does not justify a broker; APScheduler covers it
  and `refresh_job` is callable from Celery unchanged if that changes.
- **Authentication** — see item 6 above; a decision, not an oversight.
- **Monthly and intraday frequencies** — SRS 5.2 lists them as future.
- **Alerts delivery** (email/Telegram/WhatsApp) — SRS 24 marks it future-ready; detection
  and storage exist, delivery does not.
- **Backtesting and portfolio allocation** — SRS 42–44, explicitly out of MVP scope. The
  data architecture supports them: `rrg_values` is keyed by date/sector/params and the
  engine is a pure function, so a backtest can replay history without look-ahead.
