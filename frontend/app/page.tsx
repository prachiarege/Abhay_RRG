"use client";

/**
 * Main screen (SRS 13, 48).
 *
 * Layout: header, control rail on the left, RRG chart filling the centre with the playback
 * scrubber beneath it, and the sortable ranking table docked below. Clicking a sector -- on
 * the chart or in the table -- selects it, dims the rest, and opens the detail drawer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ControlPanel } from "@/components/ControlPanel";
import { Header } from "@/components/Header";
import { PlaybackBar } from "@/components/PlaybackBar";
import { RRGChart, type RRGChartHandle } from "@/components/RRGChart";
import { SectorDetailDrawer } from "@/components/SectorDetailDrawer";
import { SectorTable } from "@/components/SectorTable";
import { AbortedError, ApiError, api } from "@/lib/api";
import { QUADRANT_ORDER, QUADRANT_STYLE } from "@/lib/format";
import type {
  AppConfig,
  BenchmarkMeta,
  ConstituentsResponse,
  ControlState,
  HealthResponse,
  RRGResponse,
  SectorMeta,
} from "@/lib/types";

const INITIAL_STATE: ControlState = {
  benchmark: "NIFTY500",
  frequency: "weekly",
  tail: 10,
  sectors: [],
  level: "sector",
  drillSector: null,
  stocksBySector: {},
  asOf: null,
  rsPeriod: 14,
  momentumPeriod: 10,
  smoothingPeriod: 5,
  smoothingMethod: "sma",
  showTail: true,
  showLabels: true,
  showArrows: true,
  includePartial: false,
};

/** Debounce for parameter edits, so typing in a number field does not spam the API. */
const REQUEST_DEBOUNCE_MS = 220;

export default function Page() {
  const [state, setState] = useState<ControlState>(INITIAL_STATE);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [sectors, setSectors] = useState<SectorMeta[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkMeta[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const [data, setData] = useState<RRGResponse | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [drawerSymbol, setDrawerSymbol] = useState<string | null>(null);
  const [constituents, setConstituents] = useState<ConstituentsResponse | null>(null);
  const [constituentsLoading, setConstituentsLoading] = useState(false);
  const [constituentsError, setConstituentsError] = useState<string | null>(null);

  const chartRef = useRef<RRGChartHandle | null>(null);

  const patch = useCallback((update: Partial<ControlState>) => {
    setState((prev) => {
      const next = { ...prev, ...update };
      // Changing anything that alters the timeline invalidates the selected date: a date
      // valid for weekly bars is usually not a daily bar, and vice versa.
      if (
        update.level !== undefined ||
        update.drillSector !== undefined ||
        update.frequency !== undefined ||
        update.benchmark !== undefined ||
        update.rsPeriod !== undefined ||
        update.momentumPeriod !== undefined ||
        update.smoothingPeriod !== undefined ||
        update.smoothingMethod !== undefined ||
        update.includePartial !== undefined
      ) {
        next.asOf = null;
      }
      return next;
    });
  }, []);

  // Bootstrap: configuration, universe and health.
  useEffect(() => {
    let cancelled = false;

    Promise.all([api.config(), api.sectors(), api.benchmarks(), api.health()])
      .then(([configResult, sectorResult, benchmarkResult, healthResult]) => {
        if (cancelled) return;
        setConfig(configResult);
        setSectors(sectorResult);
        setBenchmarks(benchmarkResult);
        setHealth(healthResult);

        const defaults = configResult.defaults;
        setState((prev) => ({
          ...prev,
          benchmark: defaults.benchmark,
          frequency: defaults.frequency,
          tail: defaults.tail_length,
          rsPeriod: defaults.rs_period,
          momentumPeriod: defaults.momentum_period,
          smoothingPeriod: defaults.smoothing_period,
          smoothingMethod: defaults.smoothing_method,
          includePartial: defaults.include_partial_week,
          sectors: sectorResult
            .filter((s) => s.is_default && s.active && s.available)
            .map((s) => s.symbol),
        }));
      })
      .catch((exc: Error) => {
        if (!cancelled) {
          setBootError(exc.message);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const ready =
    state.level === "stock"
      ? Boolean(state.drillSector) &&
        (state.stocksBySector[state.drillSector ?? ""]?.length ?? 0) > 0
      : state.sectors.length > 0;

  // Chart data. Debounced, and late responses from superseded requests are discarded.
  useEffect(() => {
    if (!ready) {
      setLoading(false);
      setData(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);

    const timer = window.setTimeout(() => {
      api
        .rrg(state, controller.signal)
        .then((result) => {
          setData(result);
          setError(null);
          setLoading(false);
        })
        .catch((exc: Error) => {
          // A superseded request leaves loading alone: the run that replaced it owns it.
          if (exc instanceof AbortedError) return;
          setError(exc instanceof ApiError ? exc.message : String(exc));
          setData(null);
          setLoading(false);
        });
    }, REQUEST_DEBOUNCE_MS);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [state, ready]);

  // Playback timeline. Independent of `asOf`, so scrubbing never refetches the track.
  const timelineKey = [
    state.benchmark,
    state.frequency,
    state.rsPeriod,
    state.momentumPeriod,
    state.smoothingPeriod,
    state.smoothingMethod,
    state.includePartial,
  ].join("|");

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();

    api
      .dates(state, controller.signal)
      .then((result) => setDates(result.dates))
      .catch((exc: Error) => {
        if (exc instanceof AbortedError) return;
        setDates([]);
      });

    return () => {
      controller.abort();
    };
    // Intentionally keyed on the timeline inputs only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timelineKey, ready]);

  // Constituents for the drilled-into sector. Selection defaults to every usable stock the
  // first time a sector is opened, then whatever the user last chose for that sector.
  useEffect(() => {
    if (state.level !== "stock" || !state.drillSector) {
      setConstituents(null);
      setConstituentsError(null);
      return;
    }
    const sector = state.drillSector;
    const controller = new AbortController();
    setConstituentsLoading(true);
    setConstituentsError(null);

    api
      .constituents(sector, controller.signal)
      .then((result) => {
        setConstituents(result);
        setState((prev) => {
          if (prev.stocksBySector[sector]?.length) return prev;
          const usable = result.stocks
            .filter((s) => s.active && s.available)
            .map((s) => s.symbol);
          return {
            ...prev,
            stocksBySector: { ...prev.stocksBySector, [sector]: usable },
          };
        });
      })
      .catch((exc: Error) => {
        if (exc instanceof AbortedError) return;
        setConstituentsError(exc.message);
        setConstituents(null);
      })
      .finally(() => setConstituentsLoading(false));

    return () => {
      controller.abort();
    };
  }, [state.level, state.drillSector]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await api.refresh();
      const [healthResult, rrgResult] = await Promise.all([api.health(), api.rrg(state)]);
      setHealth(healthResult);
      setData(rrgResult);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRefreshing(false);
    }
  }, [state]);

  const handleSelect = useCallback((symbol: string | null) => {
    setSelected(symbol);
    setDrawerSymbol(symbol);
  }, []);

  const quadrantCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const sector of data?.sectors ?? []) {
      if (sector.quadrant) counts.set(sector.quadrant, (counts.get(sector.quadrant) ?? 0) + 1);
    }
    return counts;
  }, [data]);

  if (bootError) {
    return (
      <div className="app">
        <Header config={null} health={null} refreshing={false} onRefresh={() => {}} />
        <div style={{ display: "grid", placeItems: "center", padding: 40 }}>
          <div className="error-box">
            <h4>Cannot reach the backend</h4>
            <p>{bootError}</p>
            <p style={{ marginTop: 10 }}>
              Start it with <code>uvicorn app.main:app --reload</code> from the{" "}
              <code>backend/</code> directory, then reload this page.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <Header
        config={config}
        health={health}
        refreshing={refreshing}
        onRefresh={handleRefresh}
      />

      <div className="body">
        <ControlPanel
          state={state}
          config={config}
          sectors={sectors}
          benchmarks={benchmarks}
          warmupBars={data?.warmup_bars ?? null}
          constituents={constituents}
          constituentsLoading={constituentsLoading}
          constituentsError={constituentsError}
          onChange={patch}
        />

        <main className="main">
          <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <div className="chart-bar">
              <div className="legend">
                {QUADRANT_ORDER.map((quadrant) => (
                  <span className="legend-item" key={quadrant}>
                    <span
                      className="legend-dot"
                      style={{ background: QUADRANT_STYLE[quadrant].color }}
                      aria-hidden
                    />
                    {QUADRANT_STYLE[quadrant].label}
                    <span style={{ color: "var(--text-dim)" }}>
                      {quadrantCounts.get(quadrant) ?? 0}
                    </span>
                  </span>
                ))}
              </div>

              <div className="toolbar">
                <button
                  type="button"
                  className="btn"
                  onClick={() => chartRef.current?.resetZoom()}
                  title="Reset zoom and pan"
                >
                  Reset view
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => chartRef.current?.download("png")}
                  disabled={!data}
                >
                  PNG
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => chartRef.current?.download("svg")}
                  disabled={!data}
                >
                  SVG
                </button>
                <a
                  className="btn"
                  href={api.exportUrl(state, "csv")}
                  aria-disabled={!data}
                  title="Export the plotted values as CSV"
                >
                  CSV
                </a>
                <a
                  className="btn primary"
                  href={api.exportUrl(state, "xlsx")}
                  aria-disabled={!data}
                  title="Export as Excel, including a parameters sheet"
                >
                  Excel
                </a>
              </div>
            </div>

            <div className="chart-panel">
              <RRGChart
                ref={chartRef}
                data={data}
                showTail={state.showTail}
                showLabels={state.showLabels}
                showArrows={state.showArrows}
                selected={selected}
                onSelect={handleSelect}
              />

              {(loading || error || !ready) && (
                <div className="chart-overlay">
                  {error ? (
                    <div className="error-box">
                      <h4>Cannot draw the graph</h4>
                      <p>{error}</p>
                    </div>
                  ) : !ready ? (
                    <div style={{ color: "var(--text-muted)", fontSize: 12, maxWidth: 340 }}>
                      {state.level === "stock" && !state.drillSector
                        ? "Choose a sector in the panel on the left to list its constituent stocks."
                        : "Select at least one series to plot."}
                    </div>
                  ) : (
                    <div>
                      <div className="spinner" />
                      <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        {state.level === "stock" &&
                        constituents &&
                        constituents.data_loaded < constituents.count
                          ? "Downloading constituent price history…"
                          : "Calculating…"}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {data && data.level === "stock" && data.membership_as_of && (
              <p className="footnote" style={{ margin: "6px 12px 0" }}>
                Plotting {data.sectors.length} constituents of {data.sector} using index
                membership as of {data.membership_as_of}. Historical positions use today&apos;s
                members, so removed constituents are absent — see the docs on composition bias.
              </p>
            )}

            {data && data.sectors.some((s) => s.is_stale) && (
              <div className="notice" style={{ margin: "6px 12px 0" }}>
                Some sectors are plotted at an earlier date than{" "}
                <b>{data.date}</b> because the data provider has gaps in their series.
                Their positions are real but not current:
                <ul>
                  {data.sectors
                    .filter((s) => s.is_stale)
                    .map((s) => (
                      <li key={s.symbol}>
                        <b>{s.name}</b> — latest {s.date} ({s.bars_behind}{" "}
                        {data.frequency === "weekly" ? "weeks" : "sessions"} behind)
                      </li>
                    ))}
                </ul>
              </div>
            )}

            {data && data.unavailable.length > 0 && (
              <div className="notice" style={{ margin: "6px 12px 0" }}>
                {data.unavailable.length} selected sector
                {data.unavailable.length === 1 ? "" : "s"} could not be plotted:
                <ul>
                  {data.unavailable.map((item) => (
                    <li key={item.symbol}>
                      <b>{item.name}</b> — {item.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <PlaybackBar
            dates={dates}
            asOf={state.asOf}
            loading={loading}
            onChange={(date) => setState((prev) => ({ ...prev, asOf: date }))}
          />

          {data && (
            <SectorTable data={data} selected={selected} onSelect={handleSelect} />
          )}
        </main>
      </div>

      {drawerSymbol && (
        <SectorDetailDrawer
          symbol={drawerSymbol}
          state={state}
          onClose={() => {
            setDrawerSymbol(null);
            setSelected(null);
          }}
        />
      )}
    </div>
  );
}
