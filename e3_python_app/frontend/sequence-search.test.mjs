import { test } from "node:test";
import assert from "node:assert/strict";
import { combineRanges, rangePositions, regexMatches, sequenceMatches } from "./sequence-search.js";

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

test("regex matches wildcard, residue classes, alternatives and variable lengths", () => {
  assert.deepEqual(regexMatches({ sequence: "QWFAAGQWVAW", query: "qw.a[avw]" }),
    [{ start: 1, end: 5 }, { start: 7, end: 11 }]);
  assert.deepEqual(regexMatches({ sequence: "ACADAADD", query: "^AC|A+D$|AD" }),
    [{ start: 1, end: 2 }, { start: 3, end: 4 }, { start: 6, end: 7 }]);
  assert.deepEqual(regexMatches({ sequence: "QWAAAGQWA", query: "QWA{1,3}" }),
    [{ start: 1, end: 5 }, { start: 7, end: 9 }]);
});

test("regex preserves overlapping spans and makes progress past empty matches", () => {
  assert.deepEqual(regexMatches({ sequence: "AAAA", query: "A{2,3}" }),
    [{ start: 1, end: 3 }, { start: 2, end: 4 }, { start: 3, end: 4 }]);
  assert.deepEqual(regexMatches({ sequence: "ACAD", query: "(?=A)|D$" }),
    [{ start: 4, end: 4 }]);
  assert.deepEqual(regexMatches({ sequence: "ACAD", query: "W*" }), []);
  assert.deepEqual(regexMatches({ sequence: "ACAD", query: "A D" }), []);
  assert.deepEqual(regexMatches({ sequence: "ACAD", query: "QWFAA" }), []);
  assert.throws(() => regexMatches({ sequence: "ACAD", query: "[A" }), SyntaxError);
});
