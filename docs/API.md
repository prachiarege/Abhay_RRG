# API Reference

Base URL `http://localhost:8000`. Interactive OpenAPI docs at `/docs`.

Coordinate system used in every response: **x = RS-Ratio, y = RS-Momentum**, centred on
100. Leading top-right, Weakening bottom-right, Lagging bottom-left, Improving top-left.

---

## Shared RRG parameters

Accepted by `/api/rrg`, `/api/rrg/dates`, `/api/sectors/{symbol}/detail` and both export
endpoints. Omitted parameters fall back to configured defaults, not to literals.

| Parameter | Type | Default | Bounds |
|---|---|---|---|
| `benchmark` | string | `RRG_DEFAULT_BENCHMARK` | must exist in `benchmarks` |
| `frequency` | `daily` \| `weekly` | `weekly` | |
| `sectors` | CSV symbols | default universe | |
| `as_of` | `YYYY-MM-DD` | latest | |
| `tail` | int | 10 | 1–250, capped by `RRG_MAX_TAIL_LENGTH` |
| `rs_period` | int | 14 | 2–250 |
| `momentum_period` | int | 10 | 2–250 |
| `smoothing_period` | int | 5 | 1–100 |
| `smoothing_method` | `none`\|`sma`\|`ema` | `sma` | |
| `norm_period` | int | 14 | 2–250 |
| `scale_factor` | float | 1.0 | >0, ≤25 |
| `clip_sigma` | float | 3.0 | >0, ≤10 |
| `center` | float | 100.0 | >0 |
| `include_partial` | bool | false | |

### Status codes

| Code | Meaning |
|---|---|
| 200 | Success — may still contain per-sector failures in `unavailable` |
| 400 | Unknown benchmark, or no plottable sector selected |
| 404 | Unknown sector on the detail endpoint |
| 409 | Insufficient history for the requested tail and parameters, with an explanation |
| 422 | Parameter failed validation |
| 429 | Rate limit exceeded |
| 500 | `{"detail": "Unable to retrieve sector data. Please try again later."}` (SRS 46) |

**Failure isolation (SRS 46):** one sector failing never fails the request. It appears in
`unavailable` with a reason and the rest are returned normally.

---

## `GET /api/rrg`

```json
{
  "benchmark": "NIFTY500",
  "benchmark_name": "NIFTY 500",
  "frequency": "weekly",
  "date": "2026-08-14",
  "requested_as_of": null,
  "tail_length": 10,
  "center": 100.0,
  "engine_version": "1.0.0",
  "params": { "rs_period": 14, "momentum_period": 10, "smoothing_period": 5,
              "smoothing_method": "sma", "norm_period": 14, "scale_factor": 1.0,
              "clip_sigma": 3.0, "center": 100.0 },
  "params_fingerprint": "c2e8ac8b9173b2c5",
  "warmup_bars": 41,
  "bars_available": 626,
  "sectors": [
    {
      "symbol": "NIFTY_IT",
      "name": "IT",
      "short_name": "IT",
      "full_name": "NIFTY IT",
      "color": "#06b6d4",
      "rs_ratio": 101.44,
      "rs_momentum": 102.6,
      "quadrant": "Leading",
      "previous_quadrant": "Improving",
      "direction": "up_right",
      "direction_label": "Up and right (strengthening, gaining momentum)",
      "rotation_score": 88.0,
      "date": "2026-08-14",
      "bars_behind": 0,
      "is_stale": false,
      "relative_returns": { "1d": -0.11, "1w": -0.11, "1m": 10.78,
                            "3m": 4.51, "6m": 6.2, "1y": 12.4 },
      "tail": [
        { "date": "2026-06-12", "rs_ratio": 99.1, "rs_momentum": 100.4, "quadrant": "Improving" },
        { "date": "2026-08-14", "rs_ratio": 101.44, "rs_momentum": 102.6, "quadrant": "Leading" }
      ]
    }
  ],
  "unavailable": [
    { "symbol": "NIFTY_OIL_GAS", "name": "Oil & Gas",
      "reason": "sector is inactive for the configured data provider" }
  ],
  "rotations": [
    { "date": "2026-07-24", "symbol": "NIFTY_IT", "previous_quadrant": "Lagging",
      "current_quadrant": "Improving", "signal": "POSITIVE_ROTATION",
      "rs_ratio": 99.31, "rs_momentum": 100.12 }
  ],
  "score_note": "Rotation score components are percentile ranks within the selected universe, so scores are not comparable across different sector selections."
}
```

### Fields worth explaining

- **`date`** is the headline date: the most recent bar for which *any* selected sector has a
  valid point.
- **`bars_behind` / `is_stale`** — a sector is plotted at *its own* latest valid
  observation, which is not always the headline date, because real feeds have gaps. Rather
  than hiding such a sector or carrying its last value forward, the response says how far
  behind it is. Clients should mark stale sectors. This is not hypothetical: see
  `SRS_DEVIATIONS.md` §1.2.
- **`warmup_bars`** — bars consumed before the first plotted point. Rendering a `T`-period
  tail needs `warmup_bars + T − 1` bars.
- **`params_fingerprint`** — 16 hex chars over engine version + all parameters. Two
  responses with the same fingerprint are directly comparable; different fingerprints are
  not.
- **`previous_quadrant`** — the quadrant at the preceding bar, for rotation flagging.

---

## `GET /api/rrg/dates`

Dates the playback control may select (SRS 21). Excludes the warm-up window, so every
offered date renders a real chart. `as_of` is ignored here — the timeline does not depend on
the position within it.

```json
{ "benchmark": "NIFTY500", "frequency": "weekly", "warmup_bars": 41,
  "count": 586, "first": "2015-05-29", "last": "2026-08-14", "dates": ["2015-05-29", "..."] }
```

Requesting `/api/rrg?as_of=<date>` recomputes using **only data available up to that
date** — no look-ahead (SRS 50.1). The same request always returns the same values
(SRS 50.2).

---

## `GET /api/sectors/{symbol}/detail`

Full computed history plus statistics for one sector (SRS 18): `rs_ratio`, `rs_momentum`,
`quadrant`, `direction_label`, all six `relative_returns`, the last 25 `rotations`, and
`history` as one entry per computed bar (`date`, `rs`, `rs_ratio`, `rs_momentum`,
`quadrant`).

---

## `GET /api/sectors` · `GET /api/benchmarks`

Universe metadata, read from the database — never hard-coded (SRS 2.1). Optional
`include_inactive` (default true).

`available: false` means the configured provider is known not to carry the index; such rows
are excluded from refresh so no requests are wasted on them.

---

## `GET /api/config`

Effective defaults, limits (tail options, frequencies, smoothing methods), quadrant names
and score weights, so the client never hard-codes them either (SRS 40).

---

## `GET /api/health`

Status, provider, database backend, `last_updated_utc` and `last_updated_ist` (stored UTC,
rendered IST per SRS 29), per-symbol data freshness, cache statistics and the last
ingestion summary.

---

## `GET /api/rotations`

Persisted quadrant transitions, newest first. `limit` (1–1000, default 100), optional
`signal` filter (`POSITIVE_ROTATION` \| `NEGATIVE_ROTATION` \| `ROTATION`).

Populated by the scheduled refresh or `python -m scripts.ingest --rotations`.

---

## Exports

`GET /api/export/rrg.csv` and `GET /api/export/rrg.xlsx` — same parameters as `/api/rrg`.

One row per tail point. Point-in-time statistics (rotation score, direction, relative
returns) appear **only on the `is_latest` row**; repeating them on historical rows would
imply they had been recomputed for those dates, which they have not.

Both are built from the same payload the chart renders, so exported values match the screen
by construction (SRS 52.8) — asserted in `tests/test_api.py`. The Excel file carries a
second **Parameters** sheet with the engine version and fingerprint, so a saved file stays
interpretable and reproducible.

Chart image export (PNG/SVG) happens client-side.

---

## Mutating endpoints

Guarded by `X-API-Key` when `RRG_API_KEY` is set; unguarded when it is not.

| Endpoint | Purpose |
|---|---|
| `POST /api/refresh` | Fetch latest data. Body: `{"symbols": [...], "full_history": bool}`. Returns a per-symbol report plus validation detail, and clears the cache. |
| `POST /api/admin/seed?overwrite=` | Re-seed the universe. Never touches `active`/`is_default`, so operator choices survive. |
| `POST /api/admin/cache/clear?prefix=` | Drop cache entries. |
| `GET /api/admin/provider/health` | Probe the configured provider — first stop when a refresh returns nothing. |
