"use client";

/** Control rail (SRS 13.1): benchmark, universe, timeframe, engine parameters, toggles. */

import type {
  AppConfig,
  BenchmarkMeta,
  ConstituentsResponse,
  ControlState,
  Frequency,
  Level,
  SectorMeta,
  SmoothingMethod,
} from "@/lib/types";

interface Props {
  state: ControlState;
  config: AppConfig | null;
  sectors: SectorMeta[];
  benchmarks: BenchmarkMeta[];
  warmupBars: number | null;
  /** Constituents of the drilled-into sector; null while loading or at sector level. */
  constituents: ConstituentsResponse | null;
  constituentsLoading: boolean;
  constituentsError: string | null;
  onChange: (patch: Partial<ControlState>) => void;
}

export function ControlPanel({
  state,
  config,
  sectors,
  benchmarks,
  warmupBars,
  constituents,
  constituentsLoading,
  constituentsError,
  onChange,
}: Props) {
  const tailOptions = config?.limits.tail_options ?? [5, 10, 15, 20, 30, 40, 60];
  const selectable = sectors.filter((s) => s.active && s.available);
  const allSelected = state.sectors.length === selectable.length;
  const stockMode = state.level === "stock";

  const toggleSector = (symbol: string) => {
    const next = state.sectors.includes(symbol)
      ? state.sectors.filter((s) => s !== symbol)
      : [...state.sectors, symbol];
    // Never allow an empty universe: there would be nothing to plot and the API would
    // reject the request, which reads as a crash rather than as a choice.
    if (next.length === 0) return;
    onChange({ sectors: next });
  };

  const pickedStocks = state.drillSector
    ? (state.stocksBySector[state.drillSector] ?? [])
    : [];

  const usableStocks = (constituents?.stocks ?? []).filter(
    (s) => s.active && s.available,
  );

  const setStocks = (next: string[]) => {
    if (!state.drillSector || next.length === 0) return;
    onChange({
      stocksBySector: { ...state.stocksBySector, [state.drillSector]: next },
    });
  };

  const toggleStock = (symbol: string) => {
    setStocks(
      pickedStocks.includes(symbol)
        ? pickedStocks.filter((s) => s !== symbol)
        : [...pickedStocks, symbol],
    );
  };

  return (
    <aside className="rail">
      <div className="group">
        <h3>Plot</h3>
        <div className="segmented">
          {(
            [
              ["sector", "Sectors"],
              ["stock", "Stocks in a sector"],
            ] as [Level, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={state.level === value}
              onClick={() => onChange({ level: value })}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="group">
        <h3>Benchmark</h3>
        <div className="field">
          <select
            value={state.benchmark}
            onChange={(e) => onChange({ benchmark: e.target.value })}
            aria-label="Benchmark index"
          >
            {benchmarks.map((b) => (
              <option key={b.symbol} value={b.symbol} disabled={!b.active || !b.available}>
                {b.display_name}
                {!b.available ? " (no data)" : ""}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="group">
        <h3>Timeframe</h3>
        <div className="field">
          <label>Frequency</label>
          <div className="segmented">
            {(["daily", "weekly"] as Frequency[]).map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={state.frequency === f}
                onClick={() => onChange({ frequency: f })}
              >
                {f === "daily" ? "Daily" : "Weekly"}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>
            Tail length — {state.tail} {state.frequency === "weekly" ? "weeks" : "sessions"}
          </label>
          <div className="segmented">
            {tailOptions.map((t) => (
              <button
                key={t}
                type="button"
                aria-pressed={state.tail === t}
                onClick={() => onChange({ tail: t })}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <label className="toggle">
          <input
            type="checkbox"
            checked={state.includePartial}
            onChange={(e) => onChange({ includePartial: e.target.checked })}
          />
          <span>Include current part-week</span>
        </label>
      </div>

      <div className="group">
        <h3>Engine parameters</h3>
        <div className="grid-2">
          <div className="field">
            <label>RS period</label>
            <input
              type="number"
              min={2}
              max={250}
              value={state.rsPeriod}
              onChange={(e) => onChange({ rsPeriod: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Momentum</label>
            <input
              type="number"
              min={2}
              max={250}
              value={state.momentumPeriod}
              onChange={(e) => onChange({ momentumPeriod: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Smoothing</label>
            <input
              type="number"
              min={1}
              max={100}
              value={state.smoothingPeriod}
              onChange={(e) => onChange({ smoothingPeriod: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Method</label>
            <select
              value={state.smoothingMethod}
              onChange={(e) =>
                onChange({ smoothingMethod: e.target.value as SmoothingMethod })
              }
            >
              <option value="sma">SMA</option>
              <option value="ema">EMA</option>
              <option value="none">None</option>
            </select>
          </div>
        </div>

        {warmupBars !== null && (
          <p className="footnote">
            Warm-up: {warmupBars} {state.frequency === "weekly" ? "weeks" : "sessions"} of
            history are consumed before the first plotted point.
          </p>
        )}

        {state.smoothingMethod === "ema" && (
          <p className="footnote" style={{ color: "#fcd9a0" }}>
            EMA carries a seed that depends on where the series starts, so historical dates
            are not bit-reproducible. SMA is recommended for archival or backtest work.
          </p>
        )}
      </div>

      <div className="group">
        <h3>Display</h3>
        <label className="toggle">
          <input
            type="checkbox"
            checked={state.showTail}
            onChange={(e) => onChange({ showTail: e.target.checked })}
          />
          <span>Tails</span>
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={state.showLabels}
            onChange={(e) => onChange({ showLabels: e.target.checked })}
          />
          <span>Labels</span>
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={state.showArrows}
            onChange={(e) => onChange({ showArrows: e.target.checked })}
          />
          <span>Direction arrows</span>
        </label>
      </div>

      {stockMode ? (
        <div className="group">
          <h3>Sector to drill into</h3>
          <div className="field">
            {/* Single-select on purpose. Constituents of two different indices share no
                meaningful peer group, and mixing them would make the rotation score --
                which is a rank within the plotted set -- meaningless. */}
            <select
              value={state.drillSector ?? ""}
              onChange={(e) => onChange({ drillSector: e.target.value || null })}
              aria-label="Sector to drill into"
            >
              <option value="">Choose a sector…</option>
              {selectable.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.full_name}
                </option>
              ))}
            </select>
          </div>

          {!state.drillSector && (
            <p className="footnote">
              Pick a sector to list its constituent stocks, then choose which to plot
              against {state.benchmark}.
            </p>
          )}

          {state.drillSector && constituentsError && (
            <div className="notice" style={{ marginTop: 8 }}>
              {constituentsError}
            </div>
          )}

          {state.drillSector && constituentsLoading && (
            <p className="footnote">Loading constituents…</p>
          )}

          {state.drillSector && constituents && (
            <>
              <h3 style={{ marginTop: 16 }}>
                Stocks — {pickedStocks.length}/{usableStocks.length}
              </h3>

              <div className="mini-actions">
                <button
                  type="button"
                  className="link-btn"
                  disabled={pickedStocks.length === usableStocks.length}
                  onClick={() => setStocks(usableStocks.map((s) => s.symbol))}
                >
                  Select all
                </button>
                <span style={{ color: "var(--text-dim)" }}>·</span>
                <button
                  type="button"
                  className="link-btn"
                  disabled={pickedStocks.length <= 1}
                  onClick={() => setStocks(usableStocks.slice(0, 1).map((s) => s.symbol))}
                >
                  Clear
                </button>
              </div>

              {constituents.data_loaded < constituents.count && (
                <p className="footnote" style={{ color: "#fcd9a0" }}>
                  {constituents.count - constituents.data_loaded} of {constituents.count}{" "}
                  stocks have no price history yet. The first plot downloads them, which
                  takes a few seconds.
                </p>
              )}

              <div className="sector-list">
                {constituents.stocks.map((stock) => {
                  const usable = stock.active && stock.available;
                  return (
                    <label
                      key={stock.symbol}
                      className={`sector-row${usable ? "" : " disabled"}`}
                      title={
                        usable
                          ? stock.name
                          : `${stock.name} — the data provider has no series for this stock`
                      }
                    >
                      <input
                        type="checkbox"
                        checked={pickedStocks.includes(stock.symbol)}
                        disabled={!usable}
                        onChange={() => toggleStock(stock.symbol)}
                      />
                      <span
                        className="swatch"
                        style={{ background: stock.color ?? "#94a3b8" }}
                        aria-hidden
                      />
                      <span className="name">{stock.symbol}</span>
                      {!usable && (
                        <span style={{ fontSize: 9, color: "var(--text-dim)" }}>n/a</span>
                      )}
                    </label>
                  );
                })}
              </div>

              {constituents.membership_as_of && (
                <p className="footnote">
                  Index membership as of {constituents.membership_as_of}. NSE rebalances its
                  indices, so a historical view uses today&apos;s members and does not
                  reconstruct past composition.
                </p>
              )}
            </>
          )}
        </div>
      ) : (
        <div className="group">
          <h3>
            Sectors — {state.sectors.length}/{selectable.length}
          </h3>
          <div className="mini-actions">
            <button
              type="button"
              className="link-btn"
              disabled={allSelected}
              onClick={() => onChange({ sectors: selectable.map((s) => s.symbol) })}
            >
              Select all
            </button>
            <span style={{ color: "var(--text-dim)" }}>·</span>
            <button
              type="button"
              className="link-btn"
              onClick={() =>
                onChange({
                  sectors: selectable.filter((s) => s.is_default).map((s) => s.symbol),
                })
              }
            >
              Reset to default
            </button>
          </div>

          <div className="sector-list">
            {sectors.map((sector) => {
              const usable = sector.active && sector.available;
              const checked = state.sectors.includes(sector.symbol);
              return (
                <label
                  key={sector.symbol}
                  className={`sector-row${usable ? "" : " disabled"}`}
                  title={
                    usable
                      ? sector.full_name
                      : `${sector.full_name} — not carried by the configured data provider`
                  }
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!usable}
                    onChange={() => toggleSector(sector.symbol)}
                  />
                  <span
                    className="swatch"
                    style={{ background: sector.color ?? "#94a3b8" }}
                    aria-hidden
                  />
                  <span className="name">{sector.name}</span>
                  {!usable && (
                    <span style={{ fontSize: 9, color: "var(--text-dim)" }}>n/a</span>
                  )}
                </label>
              );
            })}
          </div>
        </div>
      )}
    </aside>
  );
}
