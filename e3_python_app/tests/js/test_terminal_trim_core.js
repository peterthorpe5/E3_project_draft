"use strict";

const assert = require("node:assert/strict");
const trim = require("../../src/e3app/resources/terminal_trim_core.js");

function atom(plddt) {
    return {plddt};
}

function testQualityScore() {
    assert.equal(trim.qualityScore(72.5), 72.5);
    assert.equal(trim.qualityScore("90"), 90);
    for (const value of [null, undefined, "", true, false, "bad", -1, 101, Infinity]) {
        assert.equal(trim.qualityScore(value), null);
    }
}

function testIntegerValue() {
    assert.equal(trim.integerValue("12", 3), 12);
    assert.equal(trim.integerValue(0, 3), 0);
    assert.equal(trim.integerValue("2.5", 3), 3);
    assert.equal(trim.integerValue("not-an-integer", 4), 4);
}

function testClampCounts() {
    assert.deepEqual(trim.clampCounts(3, 4, 20), {n: 3, c: 4, adjusted: false});
    assert.deepEqual(trim.clampCounts(-2, 30, 20), {n: 0, c: 19, adjusted: true});
    assert.deepEqual(trim.clampCounts(8, 8, 10), {n: 8, c: 1, adjusted: true});
    assert.deepEqual(trim.clampCounts(1, 1, 0), {n: 0, c: 0, adjusted: true});
}

function testTerminalLowConfidenceRun() {
    const atoms = [atom(30), atom(60), atom(75), atom(45), atom(40)];
    assert.equal(trim.terminalLowConfidenceRun(atoms, false, 70), 2);
    assert.equal(trim.terminalLowConfidenceRun(atoms, true, 70), 2);
    assert.equal(trim.terminalLowConfidenceRun([atom(40), atom(null), atom(30)], false, 70), 1);
    assert.equal(trim.terminalLowConfidenceRun(null, false, 70), 0);
}

function testSuggestedTrim() {
    assert.deepEqual(trim.suggestedTrim([atom(null), atom(undefined)], 70, 1), {
        available: false,
        n: 0,
        c: 0,
        threshold: 70,
        minimumRun: 1,
    });
    const atoms = [atom(20), atom(30), atom(85), atom(60), atom(40)];
    assert.deepEqual(trim.suggestedTrim(atoms, 70, 2), {
        available: true,
        n: 2,
        c: 2,
        threshold: 70,
        minimumRun: 2,
    });
    assert.deepEqual(trim.suggestedTrim(atoms, 70, 3), {
        available: true,
        n: 0,
        c: 0,
        threshold: 70,
        minimumRun: 3,
    });
    const allLow = [atom(20), atom(30), atom(40)];
    assert.deepEqual(trim.suggestedTrim(allLow, 70, 1), {
        available: true,
        n: 2,
        c: 0,
        threshold: 70,
        minimumRun: 1,
    });
}

function testConfidenceSummary() {
    assert.deepEqual(trim.confidenceSummary([atom(50), atom("70"), atom(null)]), {
        total: 3,
        available: 2,
        missing: 1,
        mean: 60,
    });
    assert.deepEqual(trim.confidenceSummary([]), {
        total: 0,
        available: 0,
        missing: 0,
        mean: null,
    });
}

function testRetainedConfidenceSummary() {
    const atoms = [atom(20), atom(40), atom(80), atom(90), atom(null), atom(30)];
    assert.deepEqual(trim.retainedConfidenceSummary(atoms, 2, 1), {
        total: 3,
        available: 2,
        missing: 1,
        mean: 85,
        n: 2,
        c: 1,
        adjusted: false,
        firstIndex: 2,
        lastIndex: 4,
    });
    assert.deepEqual(trim.retainedConfidenceSummary(atoms, 5, 5), {
        total: 1,
        available: 1,
        missing: 0,
        mean: 30,
        n: 5,
        c: 0,
        adjusted: true,
        firstIndex: 5,
        lastIndex: 5,
    });
    assert.deepEqual(trim.retainedConfidenceSummary([], 2, 3), {
        total: 0,
        available: 0,
        missing: 0,
        mean: null,
        n: 0,
        c: 0,
        adjusted: true,
        firstIndex: null,
        lastIndex: null,
    });
}

testQualityScore();
testIntegerValue();
testClampCounts();
testTerminalLowConfidenceRun();
testSuggestedTrim();
testConfidenceSummary();
testRetainedConfidenceSummary();
