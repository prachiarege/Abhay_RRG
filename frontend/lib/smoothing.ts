/**
 * Tail smoothing for the RRG (V2-RRG-001, SRS V2 §7.2).
 *
 * The requirement has two halves that pull against each other:
 *
 *   "The tail must be rendered as a smooth curve between actual RRG observations."
 *   "Interpolation must not create a visual loop or cross a quadrant in a way
 *    unsupported by the actual observations."
 *
 * Any spline through points lying either side of the centre line can bulge across it, so a
 * naive `smooth: true` satisfies the first sentence and violates the second — it invents a
 * quadrant visit that never happened, which on an RRG is a analytical claim, not a cosmetic
 * one. Centripetal Catmull-Rom removes cusps and self-intersections, and the guard below
 * additionally clamps any sample that would stray to the wrong side of a boundary its own
 * segment does not cross.
 *
 * Smoothing is strictly presentational: the returned points are never fed back into any
 * calculation, and the observation coordinates are emitted unchanged as the curve's knots.
 */

export interface Point {
  x: number;
  y: number;
}

/** Samples generated per input segment. 12 is smooth at any realistic zoom without bloating the series. */
const SAMPLES_PER_SEGMENT = 12;

/**
 * Centripetal Catmull-Rom (alpha = 0.5).
 *
 * Chosen over uniform Catmull-Rom (alpha = 0) specifically because the uniform form produces
 * cusps and self-intersections when consecutive points are unevenly spaced — exactly the
 * "visual loop" §7.2 prohibits. RRG tails are unevenly spaced by nature: a sector can barely
 * move for three weeks and then jump.
 */
const ALPHA = 0.5;

function distance(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

function catmullRomSegment(
  p0: Point,
  p1: Point,
  p2: Point,
  p3: Point,
  samples: number,
): Point[] {
  const d1 = Math.pow(distance(p0, p1), ALPHA);
  const d2 = Math.pow(distance(p1, p2), ALPHA);
  const d3 = Math.pow(distance(p2, p3), ALPHA);

  // Coincident points collapse the parameterisation; fall back to the straight segment.
  if (d1 < 1e-12 || d2 < 1e-12 || d3 < 1e-12) {
    return Array.from({ length: samples }, (_, i) => {
      const t = i / samples;
      return { x: p1.x + (p2.x - p1.x) * t, y: p1.y + (p2.y - p1.y) * t };
    });
  }

  const out: Point[] = [];
  for (let i = 0; i < samples; i += 1) {
    const t = i / samples;

    // Barry–Goldman form of the centripetal spline.
    const a1x = p0.x + ((p1.x - p0.x) * (t * d2 + d1)) / d1;
    const a1y = p0.y + ((p1.y - p0.y) * (t * d2 + d1)) / d1;
    const a2x = p1.x + (p2.x - p1.x) * t;
    const a2y = p1.y + (p2.y - p1.y) * t;
    const a3x = p2.x + ((p3.x - p2.x) * t * d2) / d3;
    const a3y = p2.y + ((p3.y - p2.y) * t * d2) / d3;

    const b1x = (a1x * (d2 - t * d2) + a2x * (t * d2 + d1)) / (d1 + d2);
    const b1y = (a1y * (d2 - t * d2) + a2y * (t * d2 + d1)) / (d1 + d2);
    const b2x = (a2x * (d2 + d3 - t * d2) + a3x * t * d2) / (d2 + d3);
    const b2y = (a2y * (d2 + d3 - t * d2) + a3y * t * d2) / (d2 + d3);

    out.push({
      x: (b1x * (d2 - t * d2) + b2x * t * d2) / d2,
      y: (b1y * (d2 - t * d2) + b2y * t * d2) / d2,
    });
  }
  return out;
}

/**
 * Clamp a sample so it cannot land on the far side of a boundary that its own segment
 * stays on.
 *
 * If both endpoints of a segment sit above the centre on an axis, no interpolated point on
 * that segment may dip below it — that would render a quadrant transition the data does not
 * contain. Where the segment genuinely crosses, the sample is left alone.
 */
function guardBoundary(sample: Point, from: Point, to: Point, centre: number): Point {
  let { x, y } = sample;

  const xBothAbove = from.x >= centre && to.x >= centre;
  const xBothBelow = from.x < centre && to.x < centre;
  if (xBothAbove) x = Math.max(x, centre);
  else if (xBothBelow) x = Math.min(x, centre - 1e-9);

  const yBothAbove = from.y >= centre && to.y >= centre;
  const yBothBelow = from.y < centre && to.y < centre;
  if (yBothAbove) y = Math.max(y, centre);
  else if (yBothBelow) y = Math.min(y, centre - 1e-9);

  return { x, y };
}

/**
 * Build a dense, smooth polyline through the given observations.
 *
 * Returns the curve as `[x, y]` pairs suitable for a chart line series. The original
 * observations are always present in the output, so the curve passes exactly through every
 * real data point (§7.2: "follows actual observation points").
 *
 * @param points observation coordinates, oldest first
 * @param centre quadrant boundary value (100 by default, but configurable per SRS §4)
 * @param enabled when false, returns the raw polyline unchanged
 */
export function smoothTail(
  points: Point[],
  centre: number,
  enabled = true,
): [number, number][] {
  if (!enabled || points.length < 3) {
    return points.map((p) => [p.x, p.y]);
  }

  // Duplicate the endpoints so the first and last real segments get a control point each,
  // rather than being left as straight stubs.
  const padded: Point[] = [points[0], ...points, points[points.length - 1]];
  const curve: [number, number][] = [];

  for (let i = 1; i < padded.length - 2; i += 1) {
    const p0 = padded[i - 1];
    const p1 = padded[i];
    const p2 = padded[i + 1];
    const p3 = padded[i + 2];

    for (const sample of catmullRomSegment(p0, p1, p2, p3, SAMPLES_PER_SEGMENT)) {
      const safe = guardBoundary(sample, p1, p2, centre);
      curve.push([safe.x, safe.y]);
    }
  }

  // Close on the exact final observation — the head of the tail is the one point a user
  // reads precisely, so it must not be an interpolated approximation.
  const last = points[points.length - 1];
  curve.push([last.x, last.y]);
  return curve;
}

/**
 * Split a curve into contiguous bands, oldest first, for age-based fading (§7.2:
 * "Older tail sections should be visually lighter").
 *
 * Bands rather than a per-point gradient because a chart line series carries one opacity;
 * a handful of overlapping series is far cheaper than one series per segment, and visually
 * indistinguishable at these sizes.
 */
export function splitIntoBands(
  curve: [number, number][],
  bands: number,
): [number, number][][] {
  if (bands <= 1 || curve.length < bands * 2) return [curve];

  const out: [number, number][][] = [];
  const size = Math.ceil(curve.length / bands);
  for (let start = 0; start < curve.length; start += size) {
    // Overlap by one point so consecutive bands join without a visible gap.
    const end = Math.min(curve.length, start + size + 1);
    const slice = curve.slice(start, end);
    if (slice.length > 1) out.push(slice);
  }
  return out;
}

/** SVG path for a proper arrowhead (V2-RRG-002: "graphical shapes/paths, not text glyphs"). */
export const ARROWHEAD_PATH =
  "path://M 0 0 L -9 4.2 L -6.4 0 L -9 -4.2 Z";

/**
 * Bearing of the final movement, in degrees counter-clockwise from east.
 *
 * Returns null when the last move is too small to imply a direction — §7.3 allows either
 * falling back to the last meaningful vector or suppressing the arrow. This walks backwards
 * to find a meaningful segment, and only suppresses if the whole tail is static.
 */
export function arrowBearing(
  points: Point[],
  minMagnitude = 1e-4,
): number | null {
  for (let i = points.length - 1; i > 0; i -= 1) {
    const dx = points[i].x - points[i - 1].x;
    const dy = points[i].y - points[i - 1].y;
    if (Math.hypot(dx, dy) >= minMagnitude) {
      return (Math.atan2(dy, dx) * 180) / Math.PI;
    }
  }
  return null;
}
