"use strict";
(function exposeTerminalTrimCore(root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    root.E3TerminalTrimCore = api;
}(typeof globalThis === "object" ? globalThis : this, function buildTerminalTrimCore() {
    /**
     * Convert a possible pLDDT value to a validated score.
     *
     * @param {*} value Candidate score.
     * @returns {number|null} A score in the inclusive 0--100 range, or null.
     */
    function qualityScore(value) {
        if (value === null || value === undefined || value === ""
                || typeof value === "boolean") return null;
        const score = Number(value);
        return Number.isFinite(score) && score >= 0 && score <= 100 ? score : null;
    }

    /**
     * Convert a possible integer to a safe fallback-backed value.
     *
     * @param {*} value Candidate integer.
     * @param {number} fallback Value returned for malformed input.
     * @returns {number} Parsed integer or the fallback.
     */
    function integerValue(value, fallback) {
        const parsed = Number(value);
        return Number.isInteger(parsed) ? parsed : fallback;
    }

    /**
     * Bound terminal counts while retaining at least one visible residue.
     *
     * @param {*} nValue Requested N-terminal count.
     * @param {*} cValue Requested C-terminal count.
     * @param {*} length Number of residues in the structure trace.
     * @returns {{n:number,c:number,adjusted:boolean}} Safe display counts.
     */
    function clampCounts(nValue, cValue, length) {
        const residueCount = Math.max(0, integerValue(length, 0));
        const maximum = Math.max(0, residueCount - 1);
        const requestedN = integerValue(nValue, 0);
        const requestedC = integerValue(cValue, 0);
        const n = Math.max(0, Math.min(maximum, requestedN));
        let c = Math.max(0, Math.min(maximum, requestedC));
        if (n + c >= residueCount && residueCount) {
            c = Math.max(0, residueCount - n - 1);
        }
        return {
            n,
            c,
            adjusted: n !== requestedN || c !== requestedC,
        };
    }

    /**
     * Count a continuous low-confidence run from one end of a trace.
     *
     * Missing pLDDT ends the run because it is not evidence of low confidence.
     *
     * @param {Array<object>} atoms Ordered C-alpha atom records.
     * @param {boolean} reverse Read from the C terminus when true.
     * @param {*} threshold Exclusive upper pLDDT limit for a low-confidence run.
     * @returns {number} Number of consecutive low-confidence terminal residues.
     */
    function terminalLowConfidenceRun(atoms, reverse, threshold) {
        if (!Array.isArray(atoms)) return 0;
        const limit = Math.max(0, Math.min(100, integerValue(threshold, 70)));
        let count = 0;
        const ordered = reverse ? [...atoms].reverse() : atoms;
        for (const atom of ordered) {
            const score = qualityScore(atom?.plddt);
            if (score === null || score >= limit) break;
            count += 1;
        }
        return count;
    }

    /**
     * Suggest reversible terminal display counts from sustained low confidence.
     *
     * @param {Array<object>} atoms Ordered C-alpha atom records.
     * @param {*} threshold Exclusive pLDDT limit for low confidence.
     * @param {*} minimumRun Minimum continuous run that may be suggested.
     * @returns {{available:boolean,n:number,c:number,threshold:number,minimumRun:number}}
     *     Validated suggestion and whether residue-level confidence is available.
     */
    function suggestedTrim(atoms, threshold, minimumRun) {
        const records = Array.isArray(atoms) ? atoms : [];
        const limit = Math.max(0, Math.min(100, integerValue(threshold, 70)));
        const minimum = Math.max(1, integerValue(minimumRun, 10));
        const available = records.some(atom => qualityScore(atom?.plddt) !== null);
        if (!available) {
            return {available: false, n: 0, c: 0, threshold: limit, minimumRun: minimum};
        }
        const rawN = terminalLowConfidenceRun(records, false, limit);
        const rawC = terminalLowConfidenceRun(records, true, limit);
        const proposed = clampCounts(
            rawN >= minimum ? rawN : 0,
            rawC >= minimum ? rawC : 0,
            records.length,
        );
        return {
            available: true,
            n: proposed.n,
            c: proposed.c,
            threshold: limit,
            minimumRun: minimum,
        };
    }

    /**
     * Summarise usable residue-level confidence without inventing missing values.
     *
     * @param {Array<object>} atoms Ordered C-alpha atom records.
     * @returns {{total:number,available:number,missing:number,mean:number|null}}
     *     Coverage and arithmetic mean for usable scores.
     */
    function confidenceSummary(atoms) {
        const records = Array.isArray(atoms) ? atoms : [];
        const scores = records
            .map(atom => qualityScore(atom?.plddt))
            .filter(score => score !== null);
        const total = records.length;
        const available = scores.length;
        const mean = available
            ? scores.reduce((sum, score) => sum + score, 0) / available
            : null;
        return {total, available, missing: total - available, mean};
    }

    return {
        clampCounts,
        confidenceSummary,
        integerValue,
        qualityScore,
        suggestedTrim,
        terminalLowConfidenceRun,
    };
}));
