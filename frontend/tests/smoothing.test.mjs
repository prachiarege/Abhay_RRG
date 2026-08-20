/**
 * Interpolation guardrail tests (SRS V2 §15.2 lists these explicitly as a required unit
 * test layer). Run with `npm run test:smoothing`, which transpiles the TS module first.
 *
 * The property that matters most: smoothing is a rendering concern and must never imply a
 * quadrant transition the observations do not contain (§7.2). Everything else here is
 * secondary to that.
 */

import assert from "node:assert/strict";
import test from "node:test";

const { smoothTail, splitIntoBands, arrowBearing, ARROWHEAD_PATH } = await import(
  "../.test-build/smoothing.js"
);

const CENTRE = 100;

test("curve passes through every observation", () => {
  const points = [
    { x: 98, y: 99 },
    { x: 99, y: 100.5 },
    { x: 101, y: 101.5 },
    { x: 102.5, y: 101 },
  ];
  const curve = smoothTail(points, CENTRE);

  for (const p of points) {
    const hit = curve.some(
      ([x, y]) => Math.abs(x - p.x) < 1e-6 && Math.abs(y - p.y) < 1e-6,
    );
    assert.ok(hit, `observation (${p.x}, ${p.y}) missing from the curve`);
  }
});

test("curve is denser than the raw polyline but ends on the real head", () => {
  const points = [
    { x: 98, y: 99 },
    { x: 99, y: 100.5 },
    { x: 101, y: 101.5 },
  ];
  const curve = smoothTail(points, CENTRE);
  assert.ok(curve.length > points.length * 5, "expected interpolated samples");

  const last = curve[curve.length - 1];
  assert.deepEqual(last, [101, 101.5], "head must be the exact final observation");
});

test("never invents a quadrant crossing the data does not contain", () => {
  // Every observation sits above the centre on x, but the y-zigzag would make a naive
  // spline bulge left of 100 between the 2nd and 3rd points. That bulge would render a
  // visit to Improving/Lagging that never happened.
  const points = [
    { x: 100.2, y: 101.5 },
    { x: 103.0, y: 100.4 },
    { x: 100.1, y: 102.6 },
    { x: 103.2, y: 101.2 },
  ];
  const curve = smoothTail(points, CENTRE);

  for (const [x] of curve) {
    assert.ok(
      x >= CENTRE - 1e-9,
      `interpolated x=${x} fell below the centre while all observations are above it`,
    );
  }
});

test("guards the y axis symmetrically", () => {
  const points = [
    { x: 98.5, y: 100.3 },
    { x: 101.5, y: 103.0 },
    { x: 98.4, y: 100.2 },
    { x: 101.6, y: 103.1 },
  ];
  const curve = smoothTail(points, CENTRE);
  for (const [, y] of curve) {
    assert.ok(y >= CENTRE - 1e-9, `interpolated y=${y} dipped below the centre`);
  }
});

test("a segment that genuinely crosses is left alone", () => {
  // Here the data really does move from left of centre to right of centre, so the curve
  // must be permitted to cross. Over-clamping would be as wrong as under-clamping.
  const points = [
    { x: 97, y: 98 },
    { x: 99, y: 99.5 },
    { x: 102, y: 101 },
    { x: 103, y: 102 },
  ];
  const curve = smoothTail(points, CENTRE);
  assert.ok(
    curve.some(([x]) => x < CENTRE) && curve.some(([x]) => x > CENTRE),
    "a real crossing must still be drawn",
  );
});

test("handles degenerate inputs without throwing", () => {
  assert.deepEqual(smoothTail([], CENTRE), []);
  assert.deepEqual(smoothTail([{ x: 100, y: 100 }], CENTRE), [[100, 100]]);
  assert.deepEqual(
    smoothTail([{ x: 100, y: 100 }, { x: 101, y: 101 }], CENTRE),
    [[100, 100], [101, 101]],
  );
  // Coincident points must not produce NaN from the centripetal parameterisation.
  const repeated = smoothTail(
    [{ x: 100, y: 100 }, { x: 100, y: 100 }, { x: 100, y: 100 }, { x: 101, y: 101 }],
    CENTRE,
  );
  for (const [x, y] of repeated) {
    assert.ok(Number.isFinite(x) && Number.isFinite(y), "NaN leaked into the curve");
  }
});

test("smoothing disabled returns the raw polyline", () => {
  const points = [
    { x: 98, y: 99 },
    { x: 99, y: 100 },
    { x: 101, y: 101 },
  ];
  assert.deepEqual(smoothTail(points, CENTRE, false), [[98, 99], [99, 100], [101, 101]]);
});

test("bands cover the curve contiguously", () => {
  const points = Array.from({ length: 10 }, (_, i) => ({
    x: 98 + i * 0.5,
    y: 99 + Math.sin(i) * 0.8,
  }));
  const curve = smoothTail(points, CENTRE);
  const bands = splitIntoBands(curve, 3);

  assert.equal(bands.length, 3);
  // Consecutive bands must share a point, or the line shows visible gaps.
  for (let i = 1; i < bands.length; i += 1) {
    const prevEnd = bands[i - 1][bands[i - 1].length - 1];
    const nextStart = bands[i][0];
    assert.deepEqual(prevEnd, nextStart, `gap between band ${i - 1} and ${i}`);
  }
});

test("arrow bearing points along the final movement", () => {
  // Due east.
  assert.equal(arrowBearing([{ x: 100, y: 100 }, { x: 101, y: 100 }]), 0);
  // Due north (data space: +y is up).
  assert.equal(arrowBearing([{ x: 100, y: 100 }, { x: 100, y: 101 }]), 90);
  // North-east.
  assert.equal(arrowBearing([{ x: 100, y: 100 }, { x: 101, y: 101 }]), 45);
  // South-west.
  assert.equal(arrowBearing([{ x: 100, y: 100 }, { x: 99, y: 99 }]), -135);
});

test("arrow falls back to the last meaningful movement", () => {
  // §7.3 permits either falling back or suppressing. We fall back, so a stalled final
  // observation still shows the direction the sector was actually travelling.
  const bearing = arrowBearing([
    { x: 100, y: 100 },
    { x: 101, y: 101 },
    { x: 101, y: 101 },
  ]);
  assert.equal(bearing, 45);
});

test("arrow suppressed only when nothing moved at all", () => {
  assert.equal(
    arrowBearing([{ x: 100, y: 100 }, { x: 100, y: 100 }, { x: 100, y: 100 }]),
    null,
  );
});

test("arrowhead is a path, not a glyph", () => {
  // V2-RRG-002 requires graphical shapes rather than text characters.
  assert.ok(ARROWHEAD_PATH.startsWith("path://"), "arrow must be an SVG path");
  assert.ok(!/[►▶→↗]/u.test(ARROWHEAD_PATH), "arrow must not be a text glyph");
});
