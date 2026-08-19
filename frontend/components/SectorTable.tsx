"use client";

/** Sector ranking table (SRS 17). Every numeric column sorts; default is RS-Ratio desc. */

import { useMemo, useState } from "react";

import {
  DIRECTION_ARROW,
  QUADRANT_STYLE,
  fmtNumber,
  fmtPercent,
  returnClass,
} from "@/lib/format";
import type { RRGResponse, SectorPoint } from "@/lib/types";

type SortKey =
  | "name"
  | "rs_ratio"
  | "rs_momentum"
  | "quadrant"
  | "rotation_score"
  | "1w"
  | "1m"
  | "3m";

interface Props {
  data: RRGResponse;
  selected: string | null;
  onSelect: (symbol: string) => void;
}

const COLUMNS: { key: SortKey; label: string; title?: string }[] = [
  { key: "name", label: "Sector" },
  { key: "rs_ratio", label: "RS-Ratio" },
  { key: "rs_momentum", label: "RS-Mom" },
  { key: "quadrant", label: "Quadrant" },
  { key: "rotation_score", label: "Score", title: "Composite rotation score, 0-100" },
  { key: "1w", label: "1W Rel" },
  { key: "1m", label: "1M Rel" },
  { key: "3m", label: "3M Rel" },
];

function valueFor(sector: SectorPoint, key: SortKey): number | string | null {
  switch (key) {
    case "name":
      return sector.name;
    case "quadrant":
      return sector.quadrant ?? "";
    case "rs_ratio":
      return sector.rs_ratio;
    case "rs_momentum":
      return sector.rs_momentum;
    case "rotation_score":
      return sector.rotation_score;
    default:
      return sector.relative_returns[key] ?? null;
  }
}

export function SectorTable({ data, selected, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("rs_ratio");
  const [ascending, setAscending] = useState(false);

  const rows = useMemo(() => {
    const copy = [...data.sectors];
    copy.sort((a, b) => {
      const left = valueFor(a, sortKey);
      const right = valueFor(b, sortKey);

      // Nulls always sink to the bottom regardless of direction: a missing value is not
      // "smallest", and letting it sort to the top would bury the real leaders.
      if (left === null && right === null) return 0;
      if (left === null) return 1;
      if (right === null) return -1;

      const comparison =
        typeof left === "string" || typeof right === "string"
          ? String(left).localeCompare(String(right))
          : left - right;
      return ascending ? comparison : -comparison;
    });
    return copy;
  }, [data.sectors, sortKey, ascending]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setAscending((prev) => !prev);
    } else {
      setSortKey(key);
      // Text sorts read naturally ascending; numbers are most useful highest-first.
      setAscending(key === "name" || key === "quadrant");
    }
  };

  return (
    <section className="table-panel">
      <div className="table-head">
        <h3>Sector ranking</h3>
        <span style={{ color: "var(--text-dim)", fontSize: 11 }}>
          {rows.length} sectors · {data.benchmark_name} · {data.frequency} ·{" "}
          {data.date ?? "–"}
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.key}
                  onClick={() => toggleSort(column.key)}
                  title={column.title ?? `Sort by ${column.label}`}
                  aria-sort={
                    sortKey === column.key
                      ? ascending
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  {column.label}
                  {sortKey === column.key && (
                    <span className="arrow">{ascending ? "▲" : "▼"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((sector) => {
              const quadrant = sector.quadrant ? QUADRANT_STYLE[sector.quadrant] : null;
              const rotated =
                sector.previous_quadrant &&
                sector.quadrant &&
                sector.previous_quadrant !== sector.quadrant;

              return (
                <tr
                  key={sector.symbol}
                  className={selected === sector.symbol ? "selected" : ""}
                  onClick={() => onSelect(sector.symbol)}
                >
                  <td>
                    <span className="cell-sector">
                      <span
                        className="swatch"
                        style={{ background: sector.color ?? "#94a3b8" }}
                        aria-hidden
                      />
                      {sector.name}
                      {sector.is_stale && (
                        <span
                          className="rotation-flag"
                          style={{ background: "#78350f55", color: "#fcd9a0" }}
                          title={
                            `Data ends ${sector.date}, ` +
                            `${sector.bars_behind} bar(s) before the chart date. ` +
                            `The provider has a gap in this series.`
                          }
                        >
                          stale {sector.date}
                        </span>
                      )}
                      {rotated && (
                        <span
                          className="rotation-flag"
                          style={{
                            background: `${quadrant?.color ?? "#94a3b8"}22`,
                            color: quadrant?.color ?? "#94a3b8",
                          }}
                          title={`Moved from ${sector.previous_quadrant} to ${sector.quadrant}`}
                        >
                          {sector.previous_quadrant} →
                        </span>
                      )}
                    </span>
                  </td>
                  <td>{fmtNumber(sector.rs_ratio)}</td>
                  <td>{fmtNumber(sector.rs_momentum)}</td>
                  <td>
                    {quadrant && (
                      <span
                        className="pill"
                        style={{ background: `${quadrant.color}1f`, color: quadrant.color }}
                      >
                        {quadrant.label}
                      </span>
                    )}{" "}
                    <span
                      title={sector.direction_label}
                      style={{ color: "var(--text-muted)" }}
                    >
                      {sector.direction ? DIRECTION_ARROW[sector.direction] : ""}
                    </span>
                  </td>
                  <td>{fmtNumber(sector.rotation_score, 1)}</td>
                  <td className={returnClass(sector.relative_returns["1w"])}>
                    {fmtPercent(sector.relative_returns["1w"])}
                  </td>
                  <td className={returnClass(sector.relative_returns["1m"])}>
                    {fmtPercent(sector.relative_returns["1m"])}
                  </td>
                  <td className={returnClass(sector.relative_returns["3m"])}>
                    {fmtPercent(sector.relative_returns["3m"])}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
