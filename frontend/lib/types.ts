/**
 * API types mirroring the backend responses.
 *
 * Coordinate system, used identically here, in the API and in the docs:
 * x = RS-Ratio, y = RS-Momentum, centred on 100.
 * Leading top-right, Weakening bottom-right, Lagging bottom-left, Improving top-left.
 */

export type Quadrant = "Leading" | "Weakening" | "Lagging" | "Improving";

export type Frequency = "daily" | "weekly";

/** What the chart plots: sector indices, or the constituents of one sector. */
export type Level = "sector" | "stock";

export type SmoothingMethod = "none" | "sma" | "ema";

export type DirectionCode =
  | "right"
  | "up_right"
  | "up"
  | "up_left"
  | "left"
  | "down_left"
  | "down"
  | "down_right"
  | "flat";

export interface TailPoint {
  date: string;
  rs_ratio: number | null;
  rs_momentum: number | null;
  quadrant: Quadrant | null;
}

export type ReturnWindow = "1d" | "1w" | "1m" | "3m" | "6m" | "1y";

export type RelativeReturns = Partial<Record<ReturnWindow, number | null>>;

export interface SectorPoint {
  symbol: string;
  name: string;
  short_name: string;
  full_name: string;
  color: string | null;
  rs_ratio: number | null;
  rs_momentum: number | null;
  quadrant: Quadrant | null;
  previous_quadrant: Quadrant | null;
  direction: DirectionCode | null;
  direction_label: string;
  rotation_score: number | null;
  date: string;
  relative_returns: RelativeReturns;
  tail: TailPoint[];
  /** Benchmark bars between this sector's latest valid point and the chart's headline date. */
  bars_behind: number | null;
  /** True when this sector's data stops short of the headline date (a real feed gap). */
  is_stale: boolean;
  level: Level;
  /** For a stock, the sector it was drilled into from. */
  parent_sector: string | null;
  /** Date of the index-membership snapshot this constituent came from. */
  membership_as_of: string | null;
}

/** One index constituent, for the drill-down picker. */
export interface ConstituentStock {
  symbol: string;
  name: string;
  color: string | null;
  active: boolean;
  /** False once the provider has been asked and had no series for this stock. */
  available: boolean;
  /** Whether prices are already stored, so the UI can warn about a first-load delay. */
  data_loaded: boolean;
  latest_date: string | null;
}

export interface ConstituentsResponse {
  sector: string;
  sector_name: string;
  membership_as_of: string | null;
  count: number;
  data_loaded: number;
  stocks: ConstituentStock[];
}

export interface UnavailableSector {
  symbol: string;
  name: string;
  reason: string;
}

export interface RotationEvent {
  date: string;
  symbol: string;
  previous_quadrant: Quadrant;
  current_quadrant: Quadrant;
  signal: "POSITIVE_ROTATION" | "NEGATIVE_ROTATION" | "ROTATION";
  rs_ratio: number;
  rs_momentum: number;
}

export interface EngineParams {
  rs_period: number;
  momentum_period: number;
  smoothing_period: number;
  smoothing_method: SmoothingMethod;
  norm_period: number;
  scale_factor: number;
  clip_sigma: number;
  center: number;
}

export interface RRGResponse {
  benchmark: string;
  benchmark_name: string;
  level: Level;
  sector: string | null;
  membership_as_of: string | null;
  frequency: Frequency;
  date: string | null;
  requested_as_of: string | null;
  tail_length: number;
  center: number;
  engine_version: string;
  params: EngineParams;
  params_fingerprint: string;
  warmup_bars: number;
  bars_available: number;
  sectors: SectorPoint[];
  unavailable: UnavailableSector[];
  rotations: RotationEvent[];
  score_note: string;
}

export interface SectorMeta {
  symbol: string;
  name: string;
  short_name: string;
  full_name: string;
  color: string | null;
  is_default: boolean;
  active: boolean;
  provider_symbol: string;
  available: boolean;
}

export interface BenchmarkMeta {
  symbol: string;
  name: string;
  display_name: string;
  is_default: boolean;
  active: boolean;
  available: boolean;
}

export interface AppConfig {
  app_name: string;
  engine_version: string;
  quadrants: Quadrant[];
  provider: string;
  defaults: {
    benchmark: string;
    frequency: Frequency;
    tail_length: number;
    display_history: string;
    rs_period: number;
    momentum_period: number;
    smoothing_period: number;
    smoothing_method: SmoothingMethod;
    norm_period: number;
    scale_factor: number;
    clip_sigma: number;
    center: number;
    include_partial_week: boolean;
  };
  limits: {
    max_tail_length: number;
    tail_options: number[];
    frequencies: Frequency[];
    smoothing_methods: SmoothingMethod[];
  };
  score_weights: {
    rs_ratio: number;
    rs_momentum: number;
    momentum_change: number;
  };
  /** Presentation settings (SRS V2 Appendix A.3), served so the client hard-codes nothing. */
  rendering: RenderConfig;
  layout: {
    left: { min: number; default: number; max: number };
    bottom: { min: number; default: number; max_percent: number };
  };
}

/** Chart rendering options. Presentation only -- never affects computed values. */
export interface RenderConfig {
  tail_smooth: boolean;
  tail_interpolation: string;
  tail_line_width: number;
  tail_fade_old_points: boolean;
  tail_show_observation_dots: boolean;
  arrow_enabled: boolean;
  arrow_size: number;
  arrow_min_movement: number;
}

export interface DatesResponse {
  benchmark: string;
  frequency: Frequency;
  warmup_bars: number;
  count: number;
  first: string | null;
  last: string | null;
  dates: string[];
}

export interface HealthResponse {
  status: string;
  app: string;
  engine_version: string;
  environment: string;
  provider: string;
  database: string;
  last_updated_utc: string | null;
  last_updated_ist: string | null;
  data: { symbols: number; latest_date: string | null };
  cache: { entries: number; hits: number; misses: number; hit_rate: number | null };
  last_ingestion: Record<string, unknown> | null;
}

export interface SectorDetail {
  symbol: string;
  name: string;
  full_name: string;
  short_name: string;
  color: string | null;
  benchmark: string;
  frequency: Frequency;
  date: string;
  rs_ratio: number | null;
  rs_momentum: number | null;
  quadrant: Quadrant | null;
  direction: DirectionCode | null;
  direction_label: string;
  relative_returns: RelativeReturns;
  rotations: RotationEvent[];
  history: {
    date: string;
    rs: number | null;
    rs_ratio: number | null;
    rs_momentum: number | null;
    quadrant: Quadrant | null;
  }[];
}

/** Everything the user can change that affects the chart. */
export interface ControlState {
  benchmark: string;
  frequency: Frequency;
  tail: number;
  /** Sector symbols plotted at sector level. */
  sectors: string[];
  /** "sector" plots indices; "stock" plots one sector's constituents. */
  level: Level;
  /** Which sector is drilled into, when level === "stock". */
  drillSector: string | null;
  /** Selected constituent tickers, keyed per sector so switching back restores the choice. */
  stocksBySector: Record<string, string[]>;
  asOf: string | null;
  rsPeriod: number;
  momentumPeriod: number;
  smoothingPeriod: number;
  smoothingMethod: SmoothingMethod;
  showTail: boolean;
  showLabels: boolean;
  showArrows: boolean;
  includePartial: boolean;
}
