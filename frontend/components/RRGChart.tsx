"use client";

/**
 * The RRG plot (SRS 12, 14, 15, 16).
 *
 * ECharts is driven directly rather than through a React wrapper: the wrappers lag React
 * releases, and the imperative surface we need here (getDataURL for export, event
 * binding, resize observation) is small enough that the indirection costs more than it
 * saves.
 *
 * Orientation is fixed and matches the API exactly: x = RS-Ratio, y = RS-Momentum,
 * Leading top-right, Weakening bottom-right, Lagging bottom-left, Improving top-left.
 */

import { useEffect, useImperativeHandle, useRef, forwardRef, useCallback } from "react";
import * as echarts from "echarts";

import { DIRECTION_ROTATION, QUADRANT_STYLE } from "@/lib/format";
import type { RRGResponse, SectorPoint } from "@/lib/types";

export interface RRGChartHandle {
  /** Export the current view. SVG is re-rendered offscreen so both formats stay crisp. */
  download: (format: "png" | "svg") => void;
  resetZoom: () => void;
}

interface Props {
  data: RRGResponse | null;
  showTail: boolean;
  showLabels: boolean;
  showArrows: boolean;
  selected: string | null;
  onSelect: (symbol: string | null) => void;
}

const FALLBACK_COLOR = "#94a3b8";

/** Padding around the data so points never sit against the plot edge. */
const AXIS_PAD_MIN = 0.45;
const AXIS_PAD_RATIO = 0.16;

function sectorColor(sector: SectorPoint): string {
  return sector.color ?? FALLBACK_COLOR;
}

/**
 * Symmetric axis bounds around the centre.
 *
 * Deliberately symmetric: an asymmetric window would put the quadrant crosshair
 * off-centre and make one quadrant look larger than another, which misleads the eye
 * about how far a sector is from the boundary.
 */
function axisBounds(data: RRGResponse): { min: number; max: number } {
  const centre = data.center;
  let reach = 0;

  for (const sector of data.sectors) {
    for (const point of sector.tail) {
      if (point.rs_ratio !== null) reach = Math.max(reach, Math.abs(point.rs_ratio - centre));
      if (point.rs_momentum !== null)
        reach = Math.max(reach, Math.abs(point.rs_momentum - centre));
    }
  }

  const padded = reach + Math.max(AXIS_PAD_MIN, reach * AXIS_PAD_RATIO);
  const span = padded > 0 ? padded : 2;
  return { min: centre - span, max: centre + span };
}

function buildOption(
  data: RRGResponse,
  showTail: boolean,
  showLabels: boolean,
  showArrows: boolean,
  selected: string | null,
): echarts.EChartsOption {
  const centre = data.center;
  const { min, max } = axisBounds(data);
  const series: echarts.SeriesOption[] = [];

  // Quadrant backgrounds. Attached to an invisible series so they sit behind everything
  // and are not affected by series toggling.
  series.push({
    type: "line",
    silent: true,
    animation: false,
    data: [],
    markArea: {
      silent: true,
      itemStyle: { borderWidth: 0 },
      data: (
        [
          ["Leading", centre, centre, max, max],
          ["Weakening", centre, min, max, centre],
          ["Lagging", min, min, centre, centre],
          ["Improving", min, centre, centre, max],
        ] as const
      ).map(([name, x0, y0, x1, y1]) => [
        {
          xAxis: x0,
          yAxis: y0,
          itemStyle: { color: QUADRANT_STYLE[name].tint },
          // Quadrant names are drawn into the plot itself, so the chart is readable
          // without reference to the colour key (SRS 16, accessibility).
          label: {
            show: true,
            position: "inside",
            formatter: name.toUpperCase(),
            color: QUADRANT_STYLE[name].color,
            opacity: 0.34,
            fontSize: 11,
            fontWeight: "bold",
            letterSpacing: 1.5,
            align: x0 === min ? "left" : "right",
            verticalAlign: y1 === max ? "top" : "bottom",
            padding: 12,
          },
        },
        { xAxis: x1, yAxis: y1 },
      ]),
    },
  });

  for (const sector of data.sectors) {
    const colour = sectorColor(sector);
    const dimmed = selected !== null && selected !== sector.symbol;
    const opacity = dimmed ? 0.22 : 1;

    const points = sector.tail
      .filter((p) => p.rs_ratio !== null && p.rs_momentum !== null)
      .map((p) => [p.rs_ratio as number, p.rs_momentum as number, p.date]);

    if (points.length === 0) continue;

    // The trail: a line through the tail, thinning towards the oldest point.
    if (showTail && points.length > 1) {
      series.push({
        name: sector.symbol,
        type: "line",
        data: points,
        showSymbol: true,
        symbolSize: (_v, params) => {
          const t = params.dataIndex / Math.max(1, points.length - 1);
          return 2 + t * 3;
        },
        itemStyle: { color: colour, opacity: opacity * 0.75 },
        lineStyle: {
          color: colour,
          width: dimmed ? 1 : selected === sector.symbol ? 2.2 : 1.5,
          opacity: opacity * 0.75,
        },
        emphasis: { disabled: true },
        z: dimmed ? 2 : 3,
        animation: false,
      });
    }

    // The head: current position, labelled, optionally carrying a direction arrow.
    const head = points[points.length - 1];
    series.push({
      name: sector.symbol,
      type: "scatter",
      data: [head],
      symbol: showArrows && sector.direction && sector.direction !== "flat" ? "triangle" : "circle",
      symbolSize: selected === sector.symbol ? 15 : 11,
      symbolRotate:
        showArrows && sector.direction ? DIRECTION_ROTATION[sector.direction] - 90 : 0,
      itemStyle: {
        color: colour,
        opacity,
        borderColor: "#0b0f14",
        borderWidth: 1.5,
        shadowBlur: selected === sector.symbol ? 10 : 0,
        shadowColor: colour,
      },
      label: {
        show: showLabels,
        position: "right",
        distance: 7,
        formatter: () => sector.short_name,
        color: dimmed ? "#5f6f83" : "#e6edf5",
        fontSize: 11,
        fontWeight: selected === sector.symbol ? "bold" : "normal",
        textBorderColor: "#0b0f14",
        textBorderWidth: 3,
      },
      z: dimmed ? 4 : 6,
      animation: false,
    });
  }

  // Shared axis configuration. Left un-annotated because the two axis option types are
  // distinct in ECharts' typings; the spread is narrowed at each use site below.
  const axisCommon = {
    type: "value",
    min,
    max,
    splitLine: { lineStyle: { color: "#1a222d", type: "dashed" } },
    axisLine: { lineStyle: { color: "#2b3746" } },
    axisLabel: { color: "#5f6f83", fontSize: 10, formatter: (v: number) => v.toFixed(1) },
    axisTick: { show: false },
  };

  return {
    animation: false,
    backgroundColor: "transparent",
    grid: { left: 52, right: 34, top: 18, bottom: 44 },
    xAxis: {
      ...axisCommon,
      name: "RS-Ratio  →  relative strength",
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: "#8b9bb0", fontSize: 11 },
      // The quadrant boundary. Drawn on both axes at the configured centre, not a
      // hard-coded 100, because the centre is a configurable parameter (SRS 4).
      markLine: {
        silent: true,
        symbol: "none",
        data: [{ xAxis: centre }],
        lineStyle: { color: "#4a5a6d", width: 1.2 },
        label: { show: false },
      },
    } as echarts.XAXisComponentOption,
    yAxis: {
      ...axisCommon,
      name: "RS-Momentum  ↑",
      nameLocation: "middle",
      nameGap: 38,
      nameTextStyle: { color: "#8b9bb0", fontSize: 11 },
      markLine: {
        silent: true,
        symbol: "none",
        data: [{ yAxis: centre }],
        lineStyle: { color: "#4a5a6d", width: 1.2 },
        label: { show: false },
      },
    } as echarts.YAXisComponentOption,
    // Mouse-wheel zoom and click-drag pan on both axes (SRS 14).
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
      { type: "inside", yAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
    ],
    tooltip: {
      trigger: "item",
      backgroundColor: "#11171f",
      borderColor: "#232d3b",
      borderWidth: 1,
      padding: [8, 11],
      textStyle: { color: "#e6edf5", fontSize: 11.5 },
      formatter: (params: unknown) => {
        const p = params as { seriesName?: string; data?: unknown[] };
        const sector = data.sectors.find((s) => s.symbol === p.seriesName);
        if (!sector) return "";
        const point = p.data as [number, number, string] | undefined;
        const quadrant = sector.quadrant ? QUADRANT_STYLE[sector.quadrant] : null;
        const rows: string[] = [
          `<div style="font-weight:600;margin-bottom:5px">${sector.full_name}</div>`,
        ];
        if (point) {
          rows.push(
            `<div style="color:#8b9bb0">${point[2]}</div>`,
            `<div style="margin-top:4px">RS-Ratio <b style="font-family:monospace">${point[0].toFixed(2)}</b></div>`,
            `<div>RS-Momentum <b style="font-family:monospace">${point[1].toFixed(2)}</b></div>`,
          );
        }
        if (quadrant) {
          rows.push(
            `<div style="margin-top:4px">Quadrant <b style="color:${quadrant.color}">${quadrant.label}</b></div>`,
          );
        }
        rows.push(`<div style="color:#8b9bb0">${sector.direction_label}</div>`);

        const relative = sector.relative_returns;
        const fmt = (v: number | null | undefined) =>
          v === null || v === undefined
            ? "–"
            : `<span style="color:${v >= 0 ? "#34d399" : "#f87171"}">${v >= 0 ? "+" : ""}${v.toFixed(2)}%</span>`;
        rows.push(
          `<div style="margin-top:6px;padding-top:5px;border-top:1px solid #232d3b;color:#8b9bb0;font-size:10.5px">Relative to ${data.benchmark_name}</div>`,
          `<div style="font-family:monospace;font-size:11px">1W ${fmt(relative["1w"])} &nbsp; 1M ${fmt(relative["1m"])} &nbsp; 3M ${fmt(relative["3m"])}</div>`,
        );
        return rows.join("");
      },
    },
    series,
  };
}

export const RRGChart = forwardRef<RRGChartHandle, Props>(function RRGChart(
  { data, showTail, showLabels, showArrows, selected, onSelect },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const optionRef = useRef<echarts.EChartsOption | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Create once. Re-creating on every prop change would reset zoom and pan state.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;

    chart.on("click", (params) => {
      const symbol = (params as { seriesName?: string }).seriesName;
      if (symbol) onSelectRef.current(symbol);
    });
    // Clicking empty plot area clears the selection, which is the gesture users expect.
    chart.getZr().on("click", (event) => {
      if (!event.target) onSelectRef.current(null);
    });

    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);

    // The container is often not at its final size when the effect runs -- the grid and
    // flex rows above it are still resolving -- so ECharts would latch onto an
    // intermediate width and stretch its canvas. One deferred resize after the first
    // paint settles it.
    const frame = requestAnimationFrame(() => chart.resize());

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !data) return;
    const option = buildOption(data, showTail, showLabels, showArrows, selected);
    optionRef.current = option;
    // notMerge, so series removed by a sector deselection actually disappear.
    chart.setOption(option, { notMerge: true, lazyUpdate: false });
    // Belt and braces alongside the ResizeObserver: if the canvas and its container have
    // drifted apart for any reason, this is the cheap point at which to reconcile them.
    chart.resize();
  }, [data, showTail, showLabels, showArrows, selected]);

  const download = useCallback(
    (format: "png" | "svg") => {
      const option = optionRef.current;
      if (!option || !data) return;

      const stamp = data.date ?? "latest";
      const filename = `rrg_${data.benchmark}_${data.frequency}_${stamp}.${format}`;

      let url: string;
      let revoke: (() => void) | null = null;

      if (format === "png") {
        const chart = chartRef.current;
        if (!chart) return;
        url = chart.getDataURL({
          type: "png",
          pixelRatio: 2,
          backgroundColor: "#0b0f14",
        });
      } else {
        // ECharts can only emit SVG from an SVG-renderer instance, and the live chart
        // uses canvas for interaction performance. Rendering the same option once into a
        // detached SVG instance gives a true vector export without degrading the UI.
        const holder = document.createElement("div");
        holder.style.cssText = "position:absolute;left:-99999px;width:1200px;height:800px";
        document.body.appendChild(holder);
        const offscreen = echarts.init(holder, undefined, {
          renderer: "svg",
          width: 1200,
          height: 800,
        });
        offscreen.setOption({ ...option, backgroundColor: "#0b0f14" });
        const svg = offscreen.renderToSVGString();
        offscreen.dispose();
        holder.remove();

        const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
        url = URL.createObjectURL(blob);
        revoke = () => URL.revokeObjectURL(url);
      }

      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      revoke?.();
    },
    [data],
  );

  const resetZoom = useCallback(() => {
    chartRef.current?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  }, []);

  useImperativeHandle(ref, () => ({ download, resetZoom }), [download, resetZoom]);

  return <div ref={containerRef} className="chart" role="img" aria-label="Relative Rotation Graph" />;
});
