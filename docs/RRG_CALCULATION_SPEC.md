# RRG Calculation Specification — Engine v1.0.0

**Status:** normative. `backend/app/engine/rrg_engine.py` is the single implementation and
must agree with this document. Any change to the mathematics requires a bump to
`ENGINE_VERSION` in `backend/app/engine/params.py`.

The SRS (sections 7 and 8) specifies RS-Ratio and RS-Momentum as
`100 + normalized(...)` with "normalization method" listed as a configuration parameter.
That is a placeholder rather than a specification: it cannot be implemented unambiguously,
and it makes the SRS's own acceptance criteria (52.1 validation against a reference
dataset, 50.2 reproducibility) impossible to evaluate. This document supplies the missing
definition.

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| `S(t)` | Sector index close at bar `t` |
| `B(t)` | Benchmark index close at bar `t` |
| `n` | `rs_period` (default 14) |
| `m` | `momentum_period` (default 10) |
| `p` | `smoothing_period` (default 5) |
| `w` | `norm_period` (default 14) |
| `k` | `scale_factor` (default 1.0) |
| `σ_max` | `clip_sigma` (default 3.0) |
| `C` | `center` (default 100.0) |

All series are indexed by trading bar, ascending, at the selected frequency
(daily or weekly).

---

## 2. Alignment

The **benchmark defines the calendar** (SRS 28). A date is a trading session if and only
if the benchmark has an observation for it.

**Daily frequency.** The sector series is reindexed onto the benchmark's dates. A date the
sector is missing yields `NaN` — it is *not* forward-filled (SRS 27).

**Weekly frequency.** Both series collapse to weekly bars, but they must be matched **by
week period, not by date label**. See §7.

Missing observations propagate as `NaN` through every downstream step. They are never
imputed unless an interpolation policy is explicitly requested.

---

## 3. Relative Strength

```
RS(t) = 100 × S(t) / B(t)
```

The factor of 100 is cosmetic. Only the shape of the series matters.

`B(t) ≤ 0` yields `NaN`, never an infinity.

---

## 4. RS-Ratio

```
RS_s(t) = MA(RS, p)(t)                                  # smoothed relative strength
μ(t)    = SMA(RS_s, n)(t)                               # trailing mean
σ(t)    = StdDev(RS_s, n)(t)          [sample, ddof=1]  # trailing deviation
z(t)    = clip( (RS_s(t) − μ(t)) / σ(t), −σ_max, +σ_max )

RS-Ratio(t) = C + k · z(t)
```

`MA` is selected by `smoothing_method`: `sma`, `ema`, or `none`.

### Interpretation

**RS-Ratio > 100 means the sector's relative strength is currently above its own
`n`-period trend** — it is outperforming on a trend-relative basis.

This is the standard RRG reading and it has a consequence worth stating plainly to users:
a sector that has beaten the benchmark for five years can still plot left of centre today,
because RS-Ratio measures position relative to the sector's *own* recent trend, not
cumulative outperformance. SRS section 4's phrasing ("whether a sector is outperforming or
underperforming the benchmark") is loose in exactly this respect.

---

## 5. RS-Momentum

```
raw(t) = RS-Ratio(t) − RS-Ratio(t − m)
σ_r(t) = StdDev(raw, w)(t)            [sample, ddof=1]
z_r(t) = clip( raw(t) / σ_r(t), −σ_max, +σ_max )

RS-Momentum(t) = C + k · z_r(t)
```

### Why the momentum term is NOT de-meaned

RS-Ratio is standardised against its rolling **mean and** deviation. RS-Momentum is
standardised against its deviation **only**, deliberately.

Because `σ_r > 0`, `sign(z_r) = sign(raw)`. Therefore:

> **RS-Momentum > C if and only if RS-Ratio is higher than it was `m` bars ago.**

This is exactly what SRS 8 requires ("values above 100 represent positive momentum").
De-meaning would change the meaning to "rising faster than it has been rising lately",
under which a steadily strengthening sector could report negative momentum. Asserted in
`tests/test_rrg_engine.py::test_momentum_sign_matches_ratio_direction`, which checks the
property on every bar of an 900-bar series.

### Consequence: a steady edge is neutral momentum

A sector that beats the benchmark by a *constant* margin every bar has a monotonically
rising RS, so it plots right of centre — but its RS-Ratio saturates at a constant, so its
momentum is exactly neutral. This is correct: momentum measures the *change* in relative
strength, and an unchanging rate of gain is not accelerating.

---

## 6. Degenerate variance

A flat window leaves a rolling standard deviation of floating-point dust (~1e-15).
Dividing by dust amplifies numerical residue into a full clipped reading — which would
report a sector as *maximally weak* precisely because nothing was happening to it.

Let `floor(t) = max( MeanAbs(x, w)(t), 1.0 ) × 1e-12`. Then:

| Condition | Result |
|---|---|
| `σ > floor` | normal z-score |
| `σ ≤ floor` and `abs(numerator) ≤ floor` | `z = 0`, i.e. the centre |
| `σ ≤ floor` and `abs(numerator) > floor` | `NaN` — no defensible scale to divide by |

A sector tracking the benchmark exactly therefore plots at `(100, 100)`, which is the
intuitively right answer, rather than vanishing from the chart.

**The output is never an infinity.**

---

## 7. Weekly convention

The SRS refers to "the selected weekly convention" (section 28) without defining one.
This engine defines it:

- A week runs **Saturday through Friday** (pandas anchor `W-FRI`).
- The weekly observation is the **last actual trading day's close** within that week, and
  the bar is labelled **with that trading date** — never with the nominal Friday. A Friday
  holiday produces a Thursday-labelled bar, so no bar ever sits on a non-session date.
- **The in-progress week is excluded by default** (`include_partial_week = false`).
  Including it makes every sector's head point drift a little each day, which reads as a
  bug and makes tails non-reproducible.

### Cross-series weekly matching

Sector and benchmark weekly bars are matched **by week period**, not by date label.

This matters, and getting it wrong fails silently. If each series is resampled
independently, each bar carries its own last-trading-day label. A sector that is missing
the benchmark's Friday but traded Thursday gets a Thursday label; a reindex onto the
benchmark's Friday label then finds no match and produces `NaN` for a week in which the
sector demonstrably traded. Real feeds have patchier sector coverage than index coverage,
so this drops scattered weeks and leaves sectors plotted at stale dates.

Period matching pairs "the sector's last close that week" with "the benchmark's last close
that week". A week in which the sector genuinely has no observation still yields `NaN` —
that is a real gap, not a labelling artefact. See
`align_to_weekly_grid` and its regression tests.

---

## 8. Warm-up

```
min_bars = p + (n − 1) + m + (w − 1)
```

At defaults: `5 + 13 + 10 + 13 = 41` bars.

The first `min_bars − 1` bars carry `NaN` and are returned as such, so callers can see
exactly how much history was consumed. A request whose tail plus warm-up exceeds the
available history returns **HTTP 409 with an explanatory message** — never a silently
shortened tail.

Rendering a `T`-period tail requires `min_bars + T − 1` bars. At weekly frequency with a
60-period tail this is 100 weeks, i.e. roughly two years — materially more than the
1-year display-history default in SRS 51. **Warm-up and display history are independent
quantities** and must be configured as such.

---

## 9. Quadrants

Canonical orientation (SRS 12), used identically in the engine, the API, the UI and this
document:

```
                        RS-Momentum
                             ↑
            Improving        |        Leading
                             |
       ──────────────────────+──────────────────────→  RS-Ratio
                             |
             Lagging         |        Weakening
                             |
```

| Quadrant | RS-Ratio | RS-Momentum |
|---|---|---|
| Leading | ≥ C | ≥ C |
| Weakening | ≥ C | < C |
| Lagging | < C | < C |
| Improving | < C | ≥ C |

Boundary points resolve to the **stronger** side (`≥`), making classification total: every
finite point receives exactly one quadrant.

> **SRS section 11 is wrong.** Its diagram labels both upper quadrants "Leading" and its
> prose places Weakening top-right and Improving bottom-right. Sections 4 and 12 agree with
> each other and with this specification. Section 11 should be deleted from the SRS.

---

## 10. Direction

Computed from the **latest two observations only** (SRS 10):

```
angle = atan2( ΔRS-Momentum, ΔRS-Ratio )
```

Bucketed into eight compass directions at 45° boundaries (`right`, `up_right`, `up`,
`up_left`, `left`, `down_left`, `down`, `down_right`). A movement below 1e-9 in both axes
is `flat`.

---

## 11. Rotation signals

| Transition | Signal |
|---|---|
| Lagging → Improving | POSITIVE_ROTATION |
| Improving → Leading | POSITIVE_ROTATION |
| Weakening → Leading | POSITIVE_ROTATION |
| Leading → Weakening | NEGATIVE_ROTATION |
| Weakening → Lagging | NEGATIVE_ROTATION |
| Improving → Lagging | NEGATIVE_ROTATION |
| Any diagonal (e.g. Leading → Lagging) | ROTATION |

A `NaN` quadrant breaks the chain: a data gap never manufactures a transition when values
resume on the far side of it.

---

## 12. Relative returns

**Geometric**, in percent:

```
rel_return(τ) = ( [S(t)/S(t−τ)] / [B(t)/B(t−τ)] − 1 ) × 100
```

Windows are **calendar offsets** (1d, 1w, 1m, 3m, 6m, 1y), resolved to the last
observation at or before `t − τ`. Strictly backward-looking; never interpolated. When the
window predates the available data the result is `null`, not an approximation.

> SRS section 25 gives this as an arithmetic difference (`sector return − benchmark
> return`) while sections 14 and 18 present it as a percentage of relative performance.
> The two diverge materially over 6M and 1Y horizons and only one can match the export
> (SRS 52.8), so the geometric form is used consistently everywhere.

---

## 13. Rotation score

```
score = 0.40 · pct_rank(RS-Ratio) + 0.40 · pct_rank(RS-Momentum) + 0.20 · pct_rank(Δ RS-Momentum)
```

Weights are configurable and must sum to 1.0. Ranks are percentile ranks scaled 0–100,
ties averaged.

**The components are ranks within the selected universe, so scores are not comparable
across different sector selections** — adding or removing a sector shifts every other
score. The API returns this caveat in `score_note` and the UI displays it. A single-sector
universe scores 50 (neutral), because a percentile has no meaning without peers. The score
is supplementary and never replaces the underlying RS values (SRS 26).

---

## 14. Reproducibility guarantees

### 14.1 No look-ahead

Every transform is a trailing rolling window or a backward shift. No operation reads a
future bar. Series are truncated at `as_of` **before** the engine is called, never computed
on full history and sliced afterwards.

Enforced by `tests/test_no_lookahead.py`, which asserts across 40 sampled dates that the
value for date `D` computed from full history equals the value for `D` computed from
history truncated at `D`, and additionally that *corrupting* all data after `D` leaves
every value at or before `D` bit-identical.

### 14.2 Truncation invariance and the SMA default

`smoothing_method` defaults to **`sma`**, not `ema`, for a specific reason: an exponential
average carries a seed that depends on where the input series begins. Recomputing a
historical date from truncated data therefore gives a *slightly different* answer — the
deviation decays but never reaches zero. With SMA every operation is window-local and the
guarantee in §14.1 is exact.

`ema` remains selectable. It is not suitable for archival or backtest work, and the UI
warns when it is chosen.

### 14.3 Versioning

Every stored `rrg_values` row carries `engine_version` and a 16-character
`params_fingerprint` (SHA-256 over the engine version plus all parameters). Without these
in the primary key, precomputed rows from different parameter sets are indistinguishable —
a gap in the SRS 32 schema, given that SRS 13.1 exposes the parameters as user controls.

### 14.4 Validation tolerance

`tests/test_rrg_engine.py` contains `reference_rrg`, an independently coded NumPy
implementation using explicit loops rather than pandas rolling windows, written from this
document. The two agree to **1e-8 absolute** across 900 bars.

The tolerance is not tighter because pandas computes rolling variance with a streaming
(Welford-style) update while the reference uses a naive two-pass sum; the two accumulate
float64 error in different orders. Measured worst case is ~1.1e-9 absolute on values of
order 100 — about 1e-11 relative, at the limit of double precision and some nine orders of
magnitude below any financially meaningful difference.

This satisfies SRS 52.1. Note that it validates the implementation against *this
specification*, not against any third-party vendor's RRG. Vendors do not publish their
exact formulations, so numeric agreement with a specific commercial product is not a
testable goal; if the client requires it, they must supply a reference dataset and the
parameters will need calibration against it.

---

## 15. Default parameters

| Parameter | Default | Source |
|---|---|---|
| `rs_period` | 14 | SRS 51 |
| `momentum_period` | 10 | SRS 51 |
| `smoothing_period` | 5 | chosen (SRS says "configurable") |
| `smoothing_method` | `sma` | chosen — see §14.2 |
| `norm_period` | 14 | chosen (mirrors `rs_period`) |
| `scale_factor` | 1.0 | chosen |
| `clip_sigma` | 3.0 | chosen — SRS 8 outlier stability |
| `center` | 100.0 | SRS 4 |
| `include_partial_week` | false | chosen — see §7 |

All are configurable via environment or the admin API without a code change (SRS 40).
