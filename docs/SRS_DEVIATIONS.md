# Deviations from the SRS, and open questions

Every place this implementation departs from the SRS, with the reason. Read this alongside
`RRG_CALCULATION_SPEC.md`. Items in **§1, §7 and §9** need a decision from the client.

---

## 1. Yahoo Finance is not viable as the production data source

**Two independent problems, both verified against the live feed on 19 Aug 2026.**

### 1.1 Licensing

Yahoo's terms do not permit redistribution or commercial use. For a product shown to
investors, advisors and portfolio managers, a licensed feed (NSE Data Services or a
redistributor) is required. This is a contract and budget item with lead time, not an
engineering task.

### 1.2 Coverage and freshness — worse than expected

Of the 17 sectors in SRS 2.1, **14 resolve on Yahoo and 3 do not**: NIFTY Oil & Gas,
NIFTY Consumer Durables, NIFTY Healthcare. These are seeded `active = false` with the
reason recorded, so the gap is visible in the admin list rather than presenting as an empty
chart. Of the benchmarks in SRS 2.2, NIFTY Midcap 150 and Smallcap 250 do not resolve
either; only NIFTY Midcap 50 is available as a mid-cap proxy.

More seriously, **Yahoo stopped updating a whole class of NSE sector symbols for roughly a
month** (18 Jul – 18 Aug 2026), resuming only on 19 Aug. The split is clean:

| Fresh through 14 Aug | Stale — 31 sessions missing |
|---|---|
| NIFTY 50, 100, 500, Bank, IT, Pharma | Auto, FMCG, Metal, Realty, Media, Energy, Infra, PSU Bank, Private Bank, Commodities |

That is **7 of the 10 default on-screen sectors** a month behind. The application detects
and reports this (`is_stale` / `bars_behind` per sector, a banner, and per-row flags), so
nobody is misled — but a sector-rotation tool whose sectors are a month stale is not
usable for its purpose.

**Recommendation:** treat Yahoo as the development fixture only. For anything
client-facing, either license a feed or schedule NSE index archives into the CSV provider's
directory. The provider abstraction means this is a config change plus one class.

---

## 2. The calculation mathematics were unspecified

SRS 7 and 8 give `100 + normalized(...)` with the normalisation method as a "configuration
parameter". As written this is not implementable unambiguously, and it makes SRS 52.1
(validation against a reference dataset) and 50.2 (reproducibility) impossible to assess.

Resolved by specifying the mathematics concretely in `RRG_CALCULATION_SPEC.md`, with an
independently coded reference implementation agreeing to 1e-8 across 900 bars.

**Note on vendor agreement:** this validates the implementation against *our* written
specification. Commercial RRG products do not publish their exact formulations, so numeric
agreement with a particular vendor's chart is not a testable goal. If the client expects
the output to match a specific tool, they must supply a reference dataset and the
parameters will need calibrating against it. Worth settling before UAT.

---

## 3. SRS section 11 is incorrect — delete it

Section 11's diagram labels both upper quadrants "Leading"/"Leading-Transition", and its
prose places Weakening top-right and Improving "bottom-right/left". Sections 4 and 12 agree
with each other and are correct. The implementation follows 4 and 12 throughout.

Section 48's ASCII mockup also transposes the axis labels (RS-Momentum and RS-Ratio both on
the vertical), though its sample data rows are correct.

---

## 4. Relative return: one definition, not two

SRS 25 defines it arithmetically (`sector return − benchmark return`); sections 14 and 18
present it as a percentage of relative performance. These diverge materially over 6M/1Y
horizons, and only one can match the export (SRS 52.8).

**Geometric** is used everywhere: `(sector growth / benchmark growth − 1) × 100`.

---

## 5. Schema corrections (SRS 32)

| Change | Reason |
|---|---|
| `price_data` gets PK `(symbol, date, source)` | SRS 27 requires duplicate detection; a constraint enforces it |
| `price_data` gets `source` | SRS 5.4 mandates multi-provider but gave nowhere to record provenance |
| `rrg_values` gets `params_fingerprint` + `engine_version` in the PK | SRS 13.1 makes parameters user-controlled while 37 requires precompute and 50.3 requires versioning; without these, rows from different parameter sets are indistinguishable |

---

## 6. Definitions the SRS left open, and what was chosen

| Item | Decision | Rationale |
|---|---|---|
| Weekly convention (SRS 28: "the selected weekly convention") | Sat–Fri week; bar = last actual trading day's close, labelled with that date | Never places a bar on a non-session date |
| In-progress week | Excluded by default | Otherwise every head point drifts daily and tails are not reproducible |
| Cross-series weekly matching | By week **period**, not date label | Independent resampling silently drops weeks where a sector missed the benchmark's Friday |
| Default smoothing | `sma`, not `ema` | An EMA seed depends on where the series starts, breaking exact reproducibility of historical dates |
| Degenerate variance | Flat series → the centre; unscalable → `NaN` | Dividing by float dust would report a quiet sector as maximally weak |
| Boundary points | Resolve to the stronger quadrant (`≥`) | Makes classification total |
| Insufficient history | HTTP 409 with an explanation | A silently shortened tail looks like a working chart that is wrong |
| Rotation score scaling (SRS 26 undefined) | Percentile rank within universe | Documented as not comparable across sector selections |
| Default universe | 10 curated of 14 available | The full SRS 2.1 list is heavily collinear (Bank/FinServ/PSU/Private; Metal/Energy/Commodities/Infra) and plots as an unreadable cluster. The rest are one click away |
| Arrow overlap (SRS 10: "should not overlap excessively") | Not implemented as stated | Untestable as written. Labels are offset and the selected sector is emphasised; a real collision-avoidance layout is a follow-up if it proves necessary |

---

## 7. Still needing a client decision

1. **Data source** — §1. Blocking for production.
2. **Reference dataset for validation** — §2. Needed before UAT can be meaningful.
3. **Authentication** — SRS 39 makes accounts optional, but SRS 24 (per-user alerts) and
   SRS 40 (admin configuration) both require identity. MVP ships with no auth and an
   optional API key on mutating endpoints.
4. **Total-return vs price-return indices** — NIFTY indices exist in both variants. Sector
   and benchmark must use the same one or the RS series carries a slow dividend drift. The
   SRS does not say; this build uses whatever the provider returns (price return for Yahoo).
5. **Alert delivery channels** — detection and storage are built; email/Telegram/WhatsApp
   delivery is not (SRS 24 marks it future).
6. **Mobile** — SRS 52.4 scopes acceptance to desktop. The layout degrades gracefully below
   860px but is not a designed mobile experience. Confirm that is acceptable.

---

## 8. Findings the data itself produced

Two validation warnings from the 12-year live load turned out to be **real market events**,
not data errors — worth recording because they show the validator behaving correctly by
flagging for review rather than discarding:

- **2025-02-01, a Saturday, has a NIFTY 50 bar.** This was the genuine Union Budget special
  trading session. A fixed-holiday table cannot know about special sessions, so the
  validator warns and keeps the bar.
- **NIFTY PSU Bank moved >25% in one session on 2017-10-25.** The bank recapitalisation
  announcement. Real, and retained.

The trading calendar is therefore derived from the benchmark's own observed dates rather
than a hand-maintained holiday list, which cannot go stale. The holiday file
(`backend/config/nse_holidays.json`) is used only to suppress spurious gap warnings and
ships intentionally empty.

---

## 9. Setup assumptions made without an answer

Four build-time choices were put to the client before development started. No answer was
received (the session was non-interactive), so each was taken on the recommended default and
built in a way that keeps it cheap to reverse. Recorded here so they can be overturned
deliberately rather than discovered later.

### 9.1 Git remote — local commits, remote attached mid-build

Initially committed locally only, on the principle that pushing to a remote nobody had named
is not a decision to make on someone's behalf. The client supplied
`https://github.com/prachiarege/Abhay_RRG` during the build and it was pushed there.

*Settled.* No action needed.

### 9.2 Data provider — Yahoo as the live default

Chosen so the application works on day one with no key and no contract. CSV is the
deterministic fallback and NSE is a documented stub.

**Reversal cost:** one environment variable (`RRG_DATA_PROVIDER`) plus, for a licensed feed,
one new class in `app/providers/`. No calculation code changes.

**This one should be overturned** — see §1. It is the same decision as §7 item 1.

### 9.3 Scope — Phase 1 plus playback and rotation detection

Delivered all 18 MVP acceptance criteria (SRS 47), plus historical playback (SRS 21) and
quadrant-transition detection (SRS 23), which were nearly free once the engine was properly
causal.

Deliberately **not** built: alert delivery channels, backtesting (SRS 42–43), portfolio
allocation (SRS 44). Detection and storage for alerts exist; only delivery is missing.

**If the client expected Phase 2 in this pass**, the missing pieces are sector detail pages
beyond the current drawer, a relative-performance dashboard, custom sector groups, and alert
delivery.

### 9.4 Database — SQLite now, Postgres-ready

Chosen because the machine has no Docker, Postgres or Redis, and requiring an infrastructure
install before any code could run was not a reasonable default. Models and queries are
Postgres-compatible; caching sits behind an interface so Redis drops in.

**Reversal cost:** change `RRG_DATABASE_URL`, add Alembic. No model changes expected.

**Caveat worth stating:** SQLite has not been exercised under concurrent write load, and the
in-process cache is per-worker — so the current setup is single-worker only. Moving to
Postgres plus Redis is a prerequisite for running more than one API worker, not an
optimisation.
