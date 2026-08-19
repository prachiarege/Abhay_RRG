# UI / UX Specification

The SRS specifies screen *contents* (sections 13–18, 48) but not a visual design. This
records the design that was implemented and why, so it can be argued with rather than
guessed at.

---

## 1. Design position

This is an instrument, not a dashboard. The user is an analyst who will keep it open for
long stretches and read precise numbers off it. Three consequences:

- **The chart is the product.** Everything else recedes. Low-chrome dark slate ground, one
  accent (`#4c9aff`), and colour otherwise reserved almost entirely for quadrant and
  return semantics.
- **Density over comfort.** 13px base, tight rhythm, everything on one screen without
  scrolling. An analyst comparing ten sectors should not have to scroll or click through
  tabs to see the numbers behind the picture.
- **Numbers must not dance.** Every figure is set in a monospace face with
  `font-variant-numeric: tabular-nums`, so digits keep column alignment and a value
  changing from `99.87` to `100.12` does not shift its neighbours horizontally.

Dark by default because these screens are watched for hours next to other market tooling.

---

## 2. Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ● Indian Sector Rotation Graph    source · data through · refreshed · ↻ │  52px
├────────────┬─────────────────────────────────────────────────────────────┤
│ Benchmark  │  Leading 3  Weakening 2  Improving 1  Lagging 4    [export] │
│            │ ┌─────────────────────────────────────────────────────────┐ │
│ Timeframe  │ │  IMPROVING                              LEADING         │ │
│  freq      │ │                    ●──●──▶                              │ │
│  tail      │ │ ───────────────────────┼─────────────────────────────── │ │ flex
│            │ │                        │                                │ │
│ Parameters │ │  LAGGING                               WEAKENING        │ │
│            │ └─────────────────────────────────────────────────────────┘ │
│ Display    ├─────────────────────────────────────────────────────────────┤
│            │ |◀ ◀ ▶ ▶ ▶|  ────────●────────  14 Aug 2026  LIVE          │  41px
│ Sectors    ├─────────────────────────────────────────────────────────────┤
│  ☑ Auto    │ SECTOR RANKING                                              │
│  ☑ Bank    │ Sector    RS-Ratio▼  RS-Mom  Quadrant  Score  1W  1M  3M   │ ≤38vh
│  …         │ Realty      102.45   102.87  Leading   90.0  …              │
└────────────┴─────────────────────────────────────────────────────────────┘
```

A 268px control rail, the plot taking all remaining vertical space, the playback scrubber
directly beneath the chart it drives, and the ranking table docked below. The detail panel
slides in from the right over the chart.

**Rail on the left, not the top.** Controls are adjusted often, and a vertical rail costs
horizontal space the chart has to spare while a horizontal toolbar would cost vertical
space it does not — an RRG is roughly square, so height is the binding constraint.

**Playback under the chart, not in the rail.** It manipulates the chart's time position, so
it belongs adjacent to what it changes.

---

## 3. The chart

| Element | Treatment | Reasoning |
|---|---|---|
| Quadrant fields | 7%-opacity tint + name set into the corner at 34% opacity | Names in the plot mean the chart never depends on colour alone (SRS 16, accessibility) |
| Axis window | **Symmetric** about the centre | An asymmetric window puts the crosshair off-centre and makes one quadrant look larger, misleading the eye about distance from a boundary |
| Tail | Line with markers growing 2px → 5px toward the present | Encodes time direction without needing a legend |
| Head | 11px marker, 15px + glow when selected | |
| Arrow | Head becomes a triangle rotated to the last segment's bearing | Direction at a glance (SRS 10); toggleable |
| Label | Short name, offset right, with a 3px dark text-border | The border keeps labels legible where they cross tails |
| Selection | Chosen sector at full opacity, others at 22% | Isolates one sector without removing context |
| Centre lines | 1.2px `#4a5a6d` cross at the configured centre | Drawn at `center`, not a hard-coded 100 (SRS 4) |

Interaction: mouse-wheel zoom, click-drag pan, hover tooltip, click to select and open
detail, click empty space to clear (SRS 14). PNG export via canvas at 2× pixel ratio; SVG
export renders the same option into a detached SVG-renderer instance, so the live chart
keeps canvas performance while the export is true vector.

### Tooltip

Full index name, the point's own date, RS-Ratio, RS-Momentum, quadrant in its colour, the
direction phrase, and 1W/1M/3M relative returns with sign colouring — the SRS 14 content.

---

## 4. Colour

| Role | Colour | |
|---|---|---|
| Leading | `#22c55e` | green |
| Weakening | `#f59e0b` | amber |
| Lagging | `#ef4444` | red |
| Improving | `#3b82f6` | blue |
| Positive return | `#34d399` | |
| Negative return | `#f87171` | |

Per SRS 16, configurable and **never load-bearing on its own**: quadrant names appear in the
plot, the legend, the table pill and the tooltip; returns carry explicit `+`/`−` signs;
direction has both a glyph and a text phrase. Sector hues are stored per row in the
`sectors` table, so they are data rather than code.

---

## 5. Honesty in the interface

The design commitment that drove the most work: **the UI never presents a number as more
current or more certain than it is.**

- **Stale sectors** carry a `stale <date>` chip in the table and a banner above the chart
  naming each one and how far behind it is. This is not decorative — with the development
  data source, 7 of 10 default sectors were four weeks stale, and without this they would
  have plotted as though current.
- **Unavailable sectors** are listed with reasons rather than silently dropped. Requesting
  an inactive sector explicitly still reports it back.
- **Insufficient history** produces the backend's explanatory message, not an empty chart.
- **Warm-up cost** is stated in the rail: how much history is consumed before the first
  point.
- **The EMA caveat** appears inline when `ema` is selected, warning that historical values
  are not bit-reproducible.
- **The score caveat** ships in the payload and is shown, because a percentile-ranked score
  is not comparable across sector selections.
- **`LIVE`** marks the latest date, so it is never ambiguous whether you are looking at
  history or the present. Playback stops at the end rather than looping, for the same
  reason.

---

## 6. Table

Sticky header, every column sortable, default RS-Ratio descending (SRS 17). Clicking a row
selects the sector on the chart and opens the detail panel — the table and chart are two
views of one selection, never separate states.

Nulls always sort to the bottom regardless of direction: a missing value is not "smallest",
and letting it float to the top would bury the actual leaders.

A quadrant change since the previous bar shows an inline `<previous> →` chip, so rotations
are visible without opening anything.

---

## 7. Detail panel

Slides over from the right, Escape or scrim-click to dismiss. Four stat tiles (RS-Ratio,
RS-Momentum, quadrant, direction), all six relative-return windows, a dual-line trajectory
chart of RS-Ratio and RS-Momentum over the last 120 observations with the neutral line drawn
in, and the rotation history newest-first with signed polarity.

The trajectory chart answers a question the RRG scatter cannot: *how* a sector arrived where
it is, on a time axis.

---

## 8. Accessibility and responsiveness

- Quadrant and direction information is available without colour (see §4).
- `aria-sort` on sortable headers, `aria-pressed` on segmented controls, `aria-label` on
  icon-only buttons, `role="dialog"` on the drawer, `role="img"` with a label on the chart.
- Visible focus rings on all interactive elements.
- Escape closes the drawer.
- The page body never scrolls horizontally.

SRS 52.4 scopes acceptance to desktop. The rail narrows at 1100px and the layout stacks
below 860px so nothing breaks, but a genuine mobile experience for a dense analytical chart
is a separate design problem and is not claimed here.

---

## 9. Known UI gaps

- **Label collision.** SRS 10 asks that arrows "not overlap excessively", which is not
  testable as written. Labels are offset and selection emphasises one sector, but there is
  no collision-avoidance layout. If clustering proves a problem in use, the fix is a
  force-directed label placement pass — deferred rather than guessed at.
- **No saved views.** Parameter sets are not persistable or shareable; the URL does not
  encode state. Worth adding, and cheap, but not in SRS scope.
- **Playback speed is fixed** at 550ms per step.
