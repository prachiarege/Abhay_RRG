"use client";

/** Header (SRS 13.1): identity, data source, refresh time in IST, manual refresh. */

import type { AppConfig, HealthResponse } from "@/lib/types";

interface Props {
  config: AppConfig | null;
  health: HealthResponse | null;
  refreshing: boolean;
  onRefresh: () => void;
}

export function Header({ config, health, refreshing, onRefresh }: Props) {
  return (
    <header className="header">
      <h1>
        <span className="mark" aria-hidden />
        {config?.app_name ?? "Indian Sector Rotation Graph"}
      </h1>

      <div className="header-meta">
        <span className="header-field">
          Source <b>{health?.provider ?? config?.provider ?? "–"}</b>
        </span>
        <span className="header-field">
          Data through <b>{health?.data.latest_date ?? "–"}</b>
        </span>
        <span className="header-field">
          {/* Stored in UTC, displayed in IST (SRS 29). */}
          Refreshed <b>{health?.last_updated_ist ?? "never"}</b>
        </span>
        <span className="header-field" style={{ color: "var(--text-dim)" }}>
          engine {config?.engine_version ?? health?.engine_version ?? "–"}
        </span>
        <button
          type="button"
          className="btn"
          onClick={onRefresh}
          disabled={refreshing}
          title="Fetch the latest market data from the configured provider"
        >
          {refreshing ? "Refreshing…" : "↻ Refresh data"}
        </button>
      </div>
    </header>
  );
}
