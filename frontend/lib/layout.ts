/**
 * Workspace layout state (V2-UX-001, SRS V2 §11).
 *
 * Deliberately separate from `ControlState`: the chart-data effect is keyed on ControlState,
 * so putting panel sizes there would make every drag of a divider refetch the RRG. §11.3
 * requires the opposite — "Resizing must not trigger market-data requests or alter RRG
 * values" — and V2-AC-08/09 test for it. Keeping layout in its own state is what makes that
 * true structurally rather than by luck.
 */

/** Bounds from SRS V2 §11.4. Served from /api/config so they stay configuration, not code. */
export interface LayoutLimits {
  left: { min: number; default: number; max: number };
  bottom: { min: number; default: number; maxPercent: number };
}

export const FALLBACK_LIMITS: LayoutLimits = {
  left: { min: 220, default: 320, max: 500 },
  bottom: { min: 120, default: 250, maxPercent: 60 },
};

export interface Layout {
  leftWidth: number;
  bottomHeight: number;
}

const STORAGE_KEY = "rrg.layout.v1";

export function defaultLayout(limits: LayoutLimits): Layout {
  return { leftWidth: limits.left.default, bottomHeight: limits.bottom.default };
}

/**
 * Clamp a layout to its configured bounds and the current viewport.
 *
 * The viewport term matters: a layout persisted on a 2560px monitor would otherwise leave
 * no room for the chart when the same install is opened on a laptop. The bottom panel's
 * ceiling is a percentage of viewport height for the same reason (§11.4).
 */
export function clampLayout(
  layout: Layout,
  limits: LayoutLimits,
  viewport: { width: number; height: number },
): Layout {
  // Never let the rail squeeze the chart below something usable, even if that means
  // ignoring the configured maximum on a narrow screen.
  const leftCeiling = Math.min(limits.left.max, Math.max(limits.left.min, viewport.width - 480));
  const bottomCeiling = Math.min(
    Math.round((viewport.height * limits.bottom.maxPercent) / 100),
    Math.max(limits.bottom.min, viewport.height - 320),
  );

  return {
    leftWidth: Math.round(
      Math.min(leftCeiling, Math.max(limits.left.min, layout.leftWidth)),
    ),
    bottomHeight: Math.round(
      Math.min(bottomCeiling, Math.max(limits.bottom.min, layout.bottomHeight)),
    ),
  };
}

/** Read the persisted layout. Corrupt or stale values fall back to defaults silently. */
export function loadLayout(limits: LayoutLimits): Layout {
  if (typeof window === "undefined") return defaultLayout(limits);
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultLayout(limits);
    const parsed = JSON.parse(raw) as Partial<Layout>;
    if (
      typeof parsed.leftWidth !== "number" ||
      typeof parsed.bottomHeight !== "number" ||
      !Number.isFinite(parsed.leftWidth) ||
      !Number.isFinite(parsed.bottomHeight)
    ) {
      return defaultLayout(limits);
    }
    return clampLayout(
      { leftWidth: parsed.leftWidth, bottomHeight: parsed.bottomHeight },
      limits,
      { width: window.innerWidth, height: window.innerHeight },
    );
  } catch {
    // A malformed entry is not worth surfacing to the user; defaults are always valid.
    return defaultLayout(limits);
  }
}

export function saveLayout(layout: Layout): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    /* private browsing / quota — the app works fine without persistence */
  }
}

export function clearLayout(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
