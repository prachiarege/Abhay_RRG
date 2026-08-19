/** Typed API client. All chart-affecting parameters are encoded in the query string. */

import type {
  AppConfig,
  BenchmarkMeta,
  ConstituentsResponse,
  ControlState,
  DatesResponse,
  HealthResponse,
  RRGResponse,
  SectorDetail,
  SectorMeta,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "http://localhost:8000";

/** Thrown when a request was deliberately superseded. Callers should ignore it. */
export class AbortedError extends Error {
  constructor() {
    super("request superseded");
    this.name = "AbortedError";
  }
}

/** Error carrying the backend's own message, so the UI can show something actionable. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch (exc) {
    // A superseded request is not a failure. Distinguishing it matters: without an abort
    // the browser still sends every keystroke's worth of requests and the single-worker
    // backend chews through all of them in order, so the UI sits on a stale answer while
    // work it no longer needs completes ahead of the one it is waiting for.
    if (exc instanceof DOMException && exc.name === "AbortError") {
      throw new AbortedError();
    }
    // A network-level failure means the API is unreachable, which is a different
    // problem from a 4xx and deserves different wording.
    throw new ApiError(
      0,
      `Cannot reach the API at ${API_BASE}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* response had no JSON body; keep the status line */
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

/** Build the shared query string for every RRG-shaped endpoint. */
export function rrgParams(state: ControlState, overrides: Record<string, string> = {}) {
  const params = new URLSearchParams({
    benchmark: state.benchmark,
    frequency: state.frequency,
    tail: String(state.tail),
    rs_period: String(state.rsPeriod),
    momentum_period: String(state.momentumPeriod),
    smoothing_period: String(state.smoothingPeriod),
    smoothing_method: state.smoothingMethod,
    include_partial: String(state.includePartial),
  });
  // At stock level the `sectors` parameter carries the selected TICKERS, and `sector`
  // names the index being drilled into. The backend distinguishes them by `level`.
  if (state.level === "stock" && state.drillSector) {
    params.set("level", "stock");
    params.set("sector", state.drillSector);
    const picked = state.stocksBySector[state.drillSector] ?? [];
    if (picked.length > 0) params.set("sectors", picked.join(","));
  } else if (state.sectors.length > 0) {
    params.set("sectors", state.sectors.join(","));
  }
  if (state.asOf) params.set("as_of", state.asOf);
  for (const [key, value] of Object.entries(overrides)) params.set(key, value);
  return params;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  health: () => request<HealthResponse>("/api/health"),
  sectors: () => request<SectorMeta[]>("/api/sectors"),
  benchmarks: () => request<BenchmarkMeta[]>("/api/benchmarks"),

  rrg: (state: ControlState, signal?: AbortSignal) =>
    request<RRGResponse>(`/api/rrg?${rrgParams(state)}`, { signal }),

  /** Playback dates. `as_of` is deliberately excluded: the full timeline never changes. */
  dates: (state: ControlState, signal?: AbortSignal) => {
    const params = rrgParams(state);
    params.delete("as_of");
    return request<DatesResponse>(`/api/rrg/dates?${params}`, { signal });
  },

  constituents: (sector: string, signal?: AbortSignal) =>
    request<ConstituentsResponse>(
      `/api/sectors/${encodeURIComponent(sector)}/constituents`,
      { signal },
    ),

  sectorDetail: (symbol: string, state: ControlState) =>
    request<SectorDetail>(
      `/api/sectors/${encodeURIComponent(symbol)}/detail?${rrgParams(state)}`,
    ),

  refresh: () => request<Record<string, unknown>>("/api/refresh", { method: "POST" }),

  /** Export URLs are plain links so the browser handles the download itself. */
  exportUrl: (state: ControlState, format: "csv" | "xlsx") =>
    `${API_BASE}/api/export/rrg.${format}?${rrgParams(state)}`,
};
