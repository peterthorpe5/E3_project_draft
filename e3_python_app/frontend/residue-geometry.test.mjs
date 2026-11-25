/** Unit checks for the geometry scales and the window shared with the trace. */
import assert from "node:assert/strict";
import { mock, test } from "node:test";
import {
  FLAG_BANDS, MISSING, geometryBins, geometryDetail, geometryLegend, mountGeometryStrip,
  outlierColour, surpriseColour,
} from "./residue-geometry.js";
import { traceResidueColour } from "./structure-trace.js";

test("surprise scale retains missing, zero, intermediate and saturated scores", () => {
  for (const value of [null, NaN, Infinity, -1, "12"])
    assert.equal(surpriseColour({ value, limit: 40 }), MISSING);
  assert.equal(surpriseColour({ value: 1, limit: -1 }), MISSING);
  assert.equal(surpriseColour({ value: 0, limit: 0 }), "#f9eac5");
  assert.equal(surpriseColour({ value: 1, limit: 0 }), "#551643");
  assert.equal(surpriseColour({ value: 5, limit: 40 }), "#f4d497");
  assert.equal(surpriseColour({ value: 100, limit: 40 }), "#551643");
});

test("trace colours and legends distinguish every measurement and its unavailable state", () => {
  const residue = { n_outliers: 2, residue_score: 30, plddt: 92, worst_metric: "clashscore" };
  assert.equal(traceResidueColour({ residue, mode: "outliers" }), FLAG_BANDS[2].colour);
  assert.equal(traceResidueColour({ residue, mode: "surprise", limit: 40 }), "#a34352");
  assert.equal(traceResidueColour({ residue, mode: "plddt" }), "#1856a1");
  assert.equal(traceResidueColour({ residue, mode: "neutral" }), MISSING);
  assert.deepEqual([0, 1, 2, 9].map(count => outlierColour({ count })), FLAG_BANDS.map(b => b.colour));
  for (const count of [null, -1, 1.5, NaN]) assert.equal(outlierColour({ count }), MISSING);
  assert.equal(geometryLegend({ mode: "outliers" })[3].label, "3+ outliers");
  assert.equal(geometryLegend({ mode: "surprise", limit: 0 })[1].label, ">0 surprise");
  assert.equal(geometryLegend({ mode: "surprise", limit: 40 })[2].label, "≥40.0 surprise");
  assert.equal(geometryDetail({ residue }), "Surprise 30.00 · 2 outliers · worst clashscore");
  assert.equal(geometryDetail({ residue: { n_outliers: 1, residue_score: 0 } }), "Surprise 0.00 · 1 outlier");
  assert.match(geometryDetail({ residue: { status: "not_reported" } }), /not reported/);
  assert.equal(geometryDetail({ residue: undefined }), "Geometry unavailable");
});

test("sequence bins preserve narrow peaks, genuine zeros, flags and missing positions", () => {
  const model = new Map([[1, { residue_score: 30, n_outliers: 0 }],
    [2, { residue_score: 9, n_outliers: 2 }], [4, { residue_score: 0, n_outliers: 0 }]]);
  assert.deepEqual(geometryBins({ model, start: 1, end: 6, maxColumns: 3 }), [
    { peak: 30, flagged: true }, { peak: 0, flagged: false }, { peak: null, flagged: false },
  ]);
  assert.deepEqual(geometryBins({ model, start: 2, end: 3, maxColumns: 10 }), [
    { peak: 9, flagged: true }, { peak: null, flagged: false },
  ]);
});

test("geometry strip maps pointer, zoom and keyboard selections on a common axis", () => {
  const nodes = [], events = new Map(), attributes = new Map(), fillRect = mock.fn();
  const canvas = {
    clientWidth: 100, getContext: () => ({ scale() {}, fillRect }),
    setAttribute: (name, value) => attributes.set(name, value),
    addEventListener: (name, handler) => events.set(name, handler),
    getBoundingClientRect: () => ({ left: 10, width: 100 }),
  };
  const previous = Object.fromEntries(["document", "window", "ResizeObserver"].map(k => [k, globalThis[k]]));
  try {
    globalThis.document = { createElement: tag => tag === "canvas" ? canvas : {} };
    globalThis.window = { devicePixelRatio: 1 };
    globalThis.ResizeObserver = class { constructor(callback) { this.observe = callback; } };
    const pick = mock.fn(pos => strip.select(pos));
    const strip = mountGeometryStrip({ container: { appendChild: node => nodes.push(node) },
      model: new Map([[3, { residue: "M", residue_score: 0, n_outliers: 0 }]]),
      length: 5, limit: 10, onPick: pick });
    strip.setWindow(2, 4);
    events.get("pointermove")({ clientX: 60 });
    assert.match(nodes[1].textContent, /M3 · Surprise 0.00/);
    events.get("click")({ clientX: 60 });
    assert.equal(attributes.get("aria-valuenow"), "3");
    for (const key of ["ArrowRight", "ArrowRight", "Home", "ArrowLeft", "End", "Space"])
      events.get("keydown")({ key, preventDefault() {} });
    assert.deepEqual(pick.mock.calls.map(call => call.arguments[0]), [3, 4, 4, 2, 2, 4]);
    events.get("pointerleave")();
    assert.match(nodes[1].textContent, /Residue 4/);
    strip.select(null);
    assert.equal(attributes.get("aria-valuenow"), "2");
    assert.ok(fillRect.mock.callCount() > 0);
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
});
