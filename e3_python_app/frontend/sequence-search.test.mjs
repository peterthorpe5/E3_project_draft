import { test } from "node:test";
import assert from "node:assert/strict";
import { combineRanges, rangePositions, sequenceMatches } from "./sequence-search.js";

test("search matches both terminal positions, internal whitespace and case", () => {
  assert.deepEqual(sequenceMatches({ sequence: "QWFAAQQWFAA", query: "qw faa" }),
    [{ start: 1, end: 5 }, { start: 7, end: 11 }]);
  assert.deepEqual(sequenceMatches({ sequence: "QWFAA", query: "" }), []);
  assert.deepEqual(sequenceMatches({ sequence: "QWFAA", query: "AAAA" }), []);
  assert.throws(() => sequenceMatches({ sequence: "QWFAA", query: "Q.F" }), /amino-acid/);
});

test("overlapping matches remain individually selectable and merge for display", () => {
  const ranges = sequenceMatches({ sequence: "AAAAQAAAA", query: "AAA" });
  assert.deepEqual(ranges, [
    { start: 1, end: 3 }, { start: 2, end: 4 }, { start: 6, end: 8 }, { start: 7, end: 9 },
  ]);
  const combined = combineRanges(ranges);
  assert.deepEqual(combined, [{ start: 1, end: 4 }, { start: 6, end: 9 }]);
  assert.deepEqual([...rangePositions(combined)], [1, 2, 3, 4, 6, 7, 8, 9]);
  assert.deepEqual(combineRanges([]), []);
  assert.equal(ranges[0].end, 3);
});
