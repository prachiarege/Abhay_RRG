# Deviations from the SRS, and open questions

Every place this implementation departs from the SRS, with the reason. Read this alongside
`RRG_CALCULATION_SPEC.md`. Items in **§1, §7 and §9** need a decision from the client.

---

## 1. Data source — resolved with the NSE archive (free)

**Status: closed.** Originally recorded as the project's biggest risk. It was, and it is now
fixed at no cost.

### 1.1 What was wrong

Yahoo Finance was the only provider. Two problems:

*   **Licensing** — Yahoo's terms permit neither redistribution nor commercial use.
*   **Coverage and reliability** — 3 of the 17 SRS 2.1 sectors never resolved at all, and
    Yahoo stopped publishing a whole class of NSE sector indices between 18 Jul and 18 Aug
    2026, resuming without backfilling the gap.

The second was materially worse than "stale data". A NaN anywhere in a rolling window
nullifies that window, so a four-week hole suppressed RRG output for the hole plus the
warm-up chain behind it. Measured: **seven of ten default sectors had no valid weekly point
after 17 Jul**, and would not have recovered until roughly December.

### 1.2 The fix

NSE publishes the data itself:

```
https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv
```

One file per trading day, **161 indices**, full OHLC, free, no account. Verified against a
date inside the gap, and cross-checked against Yahoo on overlapping days:

| Index | NSE close | Yahoo close | Difference |
|---|---|---|---|
| Nifty 500 | 23386.20 | 23386.20 | 0.0000% |
| Nifty IT | 30433.05 | 30433.05 | 0.0000% |
| Nifty Bank | 57239.75 | 57239.75 | 0.0000% |

That agreement is load-bearing, not trivia: it means splicing the two sources introduces no
discontinuity in the relative-strength series. A price mismatch at the join would have shown
up as a fake jump in RS-Ratio.

**Result: zero stale sectors**, and the universe widened — Oil & Gas, Consumer Durables and
Healthcare (SRS 2.1) plus Midcap 150 and Smallcap 250 (SRS 2.2) are now available on
NSE-only mappings. 17/17 sectors, 6/6 benchmarks.

### 1.3 Why merge sources rather than pick one

Yahoo holds twelve years; NSE's day-file archive would need ~3,000 requests to reproduce
that. NSE has the missing days and is authoritative. Refusing to merge would mean choosing
between a long series with a hole and a short series without one — and the hole is far more
damaging, for the rolling-window reason above.

So sources merge in configured priority order (`nse,yahoo,csv`), higher priority winning per
date. SRS V2 6.4 forbids a series *silently* alternating between providers; the honest way
to satisfy that is to make it visible, so `source_breakdown` reports each provider's actual
contribution (not raw row counts) and `/api/health` surfaces it.

### 1.4 Dhan — evaluated, not adopted

The V2 SRS asked for Dhan. It was investigated in full and deliberately not adopted:

*   **Its Data API is a paid subscription — ₹499/month + taxes.** Historical OHLC and market
    quotes both sit behind it; without it the endpoints return `DH-902 / not subscribed`.
    The client's account did not have it active.
*   **The SRS's own credential example points at the wrong flow.** §10.3 and Appendix A.2
    specify `DHAN_API_KEY` / `DHAN_API_SECRET`, which belong to the OAuth consent flow —
    and Dhan's docs are explicit that its second step *"needs to be opened directly on a
    browser"* with credential entry plus 2FA. That cannot be automated, so it cannot satisfy
    V2-DATA-003 as written.
*   **The automatable path is TOTP:** `POST https://auth.dhan.co/app/generateAccessToken`
    with client id, Dhan PIN and a locally-computed TOTP code, returning a 24-hour token. It
    requires TOTP enabled on the account, and means storing the PIN *and* the TOTP seed
    locally — which collapses both factors into one store. Recommended location if ever
    implemented: Windows Credential Manager (DPAPI), never a file in the project tree.
*   `RenewToken` is documented as working only for tokens generated from Dhan Web, so the
    design would have to re-generate daily rather than renew.
*   Documented rate limits: Data APIs 5/sec and 100,000/day; Quote 1/sec.

**When Dhan would become worth it:** intraday RRG or live quotes, neither of which is in
scope (SRS V2 5.2 lists intraday as explicitly out). For daily index and equity closes, the
free exchange archive is both cheaper and more authoritative.

### 1.5 Remaining caveats

*   The archive is a **published file set, not a contracted API** — no SLA, browser-like
    headers needed, and NSE could restrict it. Fine for a single-user local tool; a
    commercial product should hold a licence.
*   **Licensing still needs confirming before this is client-facing.** Using publicly
    published files in an internal tool is not the same as redistributing them, but NSE does
    licence data commercially and that question is not mine to settle.
*   Equity constituents still come from Yahoo, where coverage is good and current. NSE
    bhavcopy is the equivalent free route if that ever changes.

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

---

## 10. Stock-level drill-down - an extension beyond the SRS

The SRS scopes the product to sector indices throughout (sections 2.1, 17, 47). Drilling from
a sector into its constituent stocks was requested after the MVP was built, and is therefore
an **addition to the specification** rather than an implementation of it.

It required no change to the calculation engine: a stock against a benchmark is
arithmetically identical to a sector against a benchmark. The work was a constituent data
model, an `Instrument` adapter, and UI. Worth recording because it validates what SRS 50.4
asked for - the engine takes two price series and knows nothing about what they represent.

### 10.1 Composition bias - the honest limitation

Index membership changes: NSE rebalances, companies demerge, tickers change. A stock-level
RRG drawn over history from a *current* membership snapshot shows how today's members
behaved, silently excluding anything since removed. **The historical stock-level view is not
survivorship-free**, and no static list can make it so.

The application records `as_of` on every membership row, returns it in the API, and states it
in the UI. Accurate historical work needs dated membership history from a licensed vendor.
For the actual use case - "which stocks in this sector are leading right now" - a current
snapshot is the correct input.

### 10.2 What the constituent data is

153 unique tickers across 14 sectors, from NSE index composition as of 2026-08-01. Verified
against the live provider: **148 of 153 resolve**.

The five that did not were instructive rather than merely broken:

| Ticker | Finding |
|---|---|
| `TATAMOTORS` | resolves only as **`TMPV`**, the post-demerger passenger-vehicle entity. Constituent renamed. |
| `MACROTECH` | ticker renamed to **`LODHA`**. Constituent renamed. |
| `JBCHEPHARM` | valid but roughly a month stale. Kept; the staleness flag reports it. |
| `LTIM` | LTIMindtree has no series under any symbol tried. Kept as a member, marked unavailable. |
| `TV18BRDCST` | no series; `NETWORK18` (also a member) resolves. Kept as a member, marked unavailable. |

Membership is kept even where price data is missing, because membership is a real fact. The
picker greys those two out with a reason rather than pretending they are not in the index.

Re-seeding **prunes** memberships no longer in the snapshot, so a ticker rename does not
leave behind a ghost row permanently marked unavailable. Stored prices for a pruned symbol
are left alone: harmless, and it makes re-adding free.

### 10.3 A side effect worth knowing

The provider's NSE **equity** coverage is markedly better than its NSE sector-**index**
coverage. Where 7 of 10 sector indices were four weeks stale (see 1.2), the constituent
series are current. The drill-down is therefore more reliable and fresher than the sector
view it drills into - backwards from what one would expect, and a further argument for
section 1's recommendation to replace the data source.

### 10.4 Fetch concurrency

The first version fetched constituents strictly one at a time, which took **37 seconds** for a
19-stock sector - bad enough to read as a hang. Vendor calls are latency-bound, so
`DataProvider.fetch_many` now runs 6-way concurrent, bringing a 15-stock sector to **10-14
seconds** cold and ~0.6 s warm. This also speeds up the sector-index refresh, which uses the
same method.

Concurrency is deliberately capped at 6 rather than pushed higher: free endpoints throttle or
refuse connections under load, and a fast fetch that fails is worse than a slower one that
works. Only the network calls are parallel - the returned frames are persisted on the calling
thread, because a SQLAlchemy Session is not safe to share across threads.
