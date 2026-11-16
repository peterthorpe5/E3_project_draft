import assert from "node:assert/strict";
import { test } from "node:test";
import { confidenceColour, NEUTRAL_TRACE_COLOUR } from "./structure-trace.js";

test("confidence colours follow the 0–100 pLDDT bands", () => {
  const cases = [
    [100, "#1856a1"], [90, "#1856a1"], [89.9, "#188499"], [70, "#188499"],
    [69.9, "#bc872b"], [50, "#bc872b"], [49.9, "#a95729"], [0, "#a95729"],
  ];
  for (const [value, colour] of cases) {
    assert.equal(confidenceColour({ value, enabled: true }), colour);
  }
});

test("unavailable, invalid and disabled confidence use the neutral trace colour", () => {
  for (const value of [null, undefined, "80", Number.NaN, Infinity, -1, 101]) {
    assert.equal(confidenceColour({ value, enabled: true }), NEUTRAL_TRACE_COLOUR);
  }
  assert.equal(confidenceColour({ value: 80, enabled: false }), NEUTRAL_TRACE_COLOUR);
});
