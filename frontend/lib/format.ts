/** Formatting helpers and the quadrant visual vocabulary. */

import type { DirectionCode, Quadrant } from "./types";

/**
 * Quadrant styling (SRS 16). Colours are the defaults; the app never relies on colour
 * alone -- every quadrant is also named in the legend, the table and the tooltip, which
 * is what makes it usable for colour-blind readers.
 */
export const QUADRANT_STYLE: Record<
  Quadrant,
  { color: string; tint: string; label: string; corner: string }
> = {
  Leading: {
    color: "#22c55e",
    tint: "rgba(34, 197, 94, 0.07)",
    label: "Leading",
    corner: "top-right",
  },
  Weakening: {
    color: "#f59e0b",
    tint: "rgba(245, 158, 11, 0.07)",
    label: "Weakening",
    corner: "bottom-right",
  },
  Lagging: {
    color: "#ef4444",
    tint: "rgba(239, 68, 68, 0.07)",
    label: "Lagging",
    corner: "bottom-left",
  },
  Improving: {
    color: "#3b82f6",
    tint: "rgba(59, 130, 246, 0.07)",
    label: "Improving",
    corner: "top-left",
  },
};

export const QUADRANT_ORDER: Quadrant[] = [
  "Leading",
  "Weakening",
  "Improving",
  "Lagging",
];

/** Arrow glyphs matching the eight direction buckets the API returns. */
export const DIRECTION_ARROW: Record<DirectionCode, string> = {
  right: "→",
  up_right: "↗",
  up: "↑",
  up_left: "↖",
  left: "←",
  down_left: "↙",
  down: "↓",
  down_right: "↘",
  flat: "•",
};

/** Degrees counter-clockwise from east, for rotating the arrow marker on the chart. */
export const DIRECTION_ROTATION: Record<DirectionCode, number> = {
  right: 0,
  up_right: 45,
  up: 90,
  up_left: 135,
  left: 180,
  down_left: 225,
  down: 270,
  down_right: 315,
  flat: 0,
};

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  return value.toFixed(digits);
}

/** Signed percentage, for relative returns where the sign carries the meaning. */
export function fmtPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function returnClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  if (value > 0) return "pos";
  if (value < 0) return "neg";
  return "";
}

/** "2026-08-14" -> "14 Aug 2026". Parsed as parts to avoid any timezone shifting. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${String(day).padStart(2, "0")} ${months[month - 1]} ${year}`;
}

export function signalLabel(signal: string): string {
  switch (signal) {
    case "POSITIVE_ROTATION":
      return "Positive rotation";
    case "NEGATIVE_ROTATION":
      return "Negative rotation";
    default:
      return "Rotation";
  }
}

/** Period presets (SRS 19) expressed as bar counts per frequency for the playback window. */
export const HISTORY_PRESETS: { label: string; months: number | null }[] = [
  { label: "1M", months: 1 },
  { label: "3M", months: 3 },
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "2Y", months: 24 },
  { label: "3Y", months: 36 },
  { label: "5Y", months: 60 },
  { label: "Max", months: null },
];
