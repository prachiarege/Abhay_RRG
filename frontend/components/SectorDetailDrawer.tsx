"use client";

/** Sector detail panel (SRS 18): current position, relative performance, rotation history. */

import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";

import { api } from "@/lib/api";
import {
  DIRECTION_ARROW,
  QUADRANT_STYLE,
  fmtDate,
  fmtNumber,
  fmtPercent,
  returnClass,
  signalLabel,
} from "@/lib/format";
import type { ControlState, ReturnWindow, SectorDetail } from "@/lib/types";

interface Props {
  symbol: string;
  state: ControlState;
  onClose: () => void;
}

const RETURN_ROWS: { key: ReturnWindow; label: string }[] = [
  { key: "1d", label: "1 day" },
  { key: "1w", label: "1 week" },
  { key: "1m", label: "1 month" },
  { key: "3m", label: "3 months" },
  { key: "6m", label: "6 months" },
  { key: "1y", label: "1 year" },
];

/** How many trailing observations the trajectory sparkline shows. */
const TRAJECTORY_POINTS = 120;

function TrajectoryChart({ detail }: { detail: SectorDetail }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });

    const history = detail.history.slice(-TRAJECTORY_POINTS);
    const colour = detail.color ?? "#4c9aff";

    chart.setOption({
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 42, right: 12, top: 22, bottom: 22 },
      legend: {
        data: ["RS-Ratio", "RS-Momentum"],
        top: 0,
        textStyle: { color: "#8b9bb0", fontSize: 10 },
        itemWidth: 12,
        itemHeight: 8,
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#11171f",
        borderColor: "#232d3b",
        textStyle: { color: "#e6edf5", fontSize: 11 },
      },
      xAxis: {
        type: "category",
        data: history.map((h) => h.date),
        axisLabel: { color: "#5f6f83", fontSize: 9, interval: Math.floor(history.length / 4) },
        axisLine: { lineStyle: { color: "#2b3746" } },
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: "#1a222d", type: "dashed" } },
        axisLabel: { color: "#5f6f83", fontSize: 9, formatter: (v: number) => v.toFixed(1) },
      },
      series: [
        {
          name: "RS-Ratio",
          type: "line",
          data: history.map((h) => h.rs_ratio),
          showSymbol: false,
          lineStyle: { color: colour, width: 1.6 },
          itemStyle: { color: colour },
        },
        {
          name: "RS-Momentum",
          type: "line",
          data: history.map((h) => h.rs_momentum),
          showSymbol: false,
          lineStyle: { color: "#8b9bb0", width: 1.2, type: "dashed" },
          itemStyle: { color: "#8b9bb0" },
        },
        {
          // The neutral line, so crossings are visible at a glance.
          name: "centre",
          type: "line",
          data: history.map(() => 100),
          showSymbol: false,
          silent: true,
          lineStyle: { color: "#4a5a6d", width: 1 },
          tooltip: { show: false },
        },
      ],
    });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [detail]);

  return <div ref={ref} className="mini-chart" />;
}

export function SectorDetailDrawer({ symbol, state, onClose }: Props) {
  const [detail, setDetail] = useState<SectorDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);

    api
      .sectorDetail(symbol, state)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((exc: Error) => {
        if (!cancelled) setError(exc.message);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, state]);

  // Escape closes, which is the expected gesture for an overlay panel.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const quadrant = detail?.quadrant ? QUADRANT_STYLE[detail.quadrant] : null;

  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden />
      <aside className="drawer" role="dialog" aria-label={`${symbol} detail`}>
        <div className="drawer-head">
          {detail && (
            <span
              className="swatch"
              style={{ background: detail.color ?? "#94a3b8", marginTop: 6 }}
              aria-hidden
            />
          )}
          <div>
            <h2>{detail?.full_name ?? symbol}</h2>
            <div className="drawer-sub">
              vs {detail?.benchmark ?? state.benchmark} · {state.frequency} ·{" "}
              {fmtDate(detail?.date)}
            </div>
          </div>
          <button type="button" className="close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {error && (
          <div className="error-box">
            <h4>Could not load detail</h4>
            <p>{error}</p>
          </div>
        )}

        {!detail && !error && <div className="empty">Loading…</div>}

        {detail && (
          <>
            <div className="stat-grid">
              <div className="stat">
                <div className="k">RS-Ratio</div>
                <div className="v">{fmtNumber(detail.rs_ratio)}</div>
              </div>
              <div className="stat">
                <div className="k">RS-Momentum</div>
                <div className="v">{fmtNumber(detail.rs_momentum)}</div>
              </div>
              <div className="stat">
                <div className="k">Quadrant</div>
                <div className="v" style={{ color: quadrant?.color, fontSize: 14 }}>
                  {quadrant?.label ?? "–"}
                </div>
              </div>
              <div className="stat">
                <div className="k">Direction</div>
                <div className="v" style={{ fontSize: 14 }}>
                  {detail.direction ? DIRECTION_ARROW[detail.direction] : "–"}{" "}
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {detail.direction ?? ""}
                  </span>
                </div>
              </div>
            </div>

            <h4>Relative performance</h4>
            {RETURN_ROWS.map((row) => (
              <div className="kv" key={row.key}>
                <span className="k">{row.label}</span>
                <span className={`v ${returnClass(detail.relative_returns[row.key])}`}>
                  {fmtPercent(detail.relative_returns[row.key])}
                </span>
              </div>
            ))}
            <p className="footnote">
              Geometric relative return: sector growth divided by benchmark growth over the
              window, less one.
            </p>

            <h4>Trajectory</h4>
            <TrajectoryChart detail={detail} />

            <h4>Rotation history</h4>
            {detail.rotations.length === 0 ? (
              <div className="empty">
                No quadrant changes in the available history at these parameters.
              </div>
            ) : (
              [...detail.rotations].reverse().map((event, position) => {
                const target = QUADRANT_STYLE[event.current_quadrant];
                return (
                  <div className="event" key={`${event.date}-${position}`}>
                    <span className="date">{event.date}</span>
                    <span style={{ color: "var(--text-muted)" }}>
                      {event.previous_quadrant} →{" "}
                    </span>
                    <span style={{ color: target.color, fontWeight: 600 }}>
                      {event.current_quadrant}
                    </span>
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: 10,
                        color:
                          event.signal === "POSITIVE_ROTATION"
                            ? "var(--pos)"
                            : event.signal === "NEGATIVE_ROTATION"
                              ? "var(--neg)"
                              : "var(--text-dim)",
                      }}
                    >
                      {signalLabel(event.signal)}
                    </span>
                  </div>
                );
              })
            )}

            <p className="footnote">
              Showing {detail.history.length} computed observations. Historical values are
              calculated using only data available on each date.
            </p>
          </>
        )}
      </aside>
    </>
  );
}
