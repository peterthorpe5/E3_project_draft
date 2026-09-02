"use strict";
(function initialiseE3TerminalTrimming() {
    const canvasElement = document.getElementById("viewer");
    const pairPayloadElement = document.getElementById("alignmentData");
    const groupPayloadElement = document.getElementById("reviewData");
    if (!canvasElement || (!pairPayloadElement && !groupPayloadElement)) return;
    if (document.getElementById("e3TerminalTrimControls")) return;

    const style = document.createElement("style");
    style.id = "e3TerminalTrimStyle";
    style.textContent = `
#e3TerminalTrimControls{border:1px solid #b9c9d4;border-radius:8px;margin:.85rem 0;
padding:.7rem;background:#f7fafc}#e3TerminalTrimControls h3{margin:.05rem 0 .55rem}
#e3TerminalTrimControls label{display:block;margin:.42rem 0}
#e3TerminalTrimControls input[type=number],#e3TerminalTrimControls select{
width:100%;padding:.35rem;margin-top:.18rem}#e3TerminalTrimControls input[type=range]{width:100%}
#e3TerminalTrimControls .e3-trim-grid{display:grid;grid-template-columns:1fr 1fr;gap:.45rem}
#e3TerminalTrimControls .e3-trim-actions{display:grid;grid-template-columns:1fr 1fr;gap:.4rem}
#e3TerminalTrimControls button{width:100%;padding:.42rem;margin:.15rem 0}
#e3QualityPlot{width:100%;height:118px;border:1px solid #c5d2db;border-radius:5px;
background:#fff;margin-top:.35rem}#e3TrimStatus{min-height:2.5rem}`;
    document.head.appendChild(style);

    const controls = document.createElement("section");
    controls.id = "e3TerminalTrimControls";
    controls.setAttribute("aria-label", "Terminal display controls");
    controls.innerHTML = `
<h3>Terminal display</h3>
<p class="note">Hide N- and/or C-terminal Cα residues for visual review only. This does not
change the saved model, alignment, pockets, scores or ranking.</p>
<label id="e3TargetLabel">Structure<select id="e3TrimTarget"></select></label>
<div class="e3-trim-grid">
<label>N-terminal residues to hide<input id="e3TrimN" type="number" min="0" step="1" value="0"></label>
<label>C-terminal residues to hide<input id="e3TrimC" type="number" min="0" step="1" value="0"></label>
</div>
<label>Low-confidence suggestion threshold: <output id="e3ThresholdValue">70</output>
<input id="e3TrimThreshold" type="range" min="0" max="100" step="1" value="70"></label>
<label>Minimum terminal run<input id="e3MinimumRun" type="number" min="1" step="1" value="10"></label>
<label><input id="e3ColourQuality" type="checkbox" checked> Colour Cα residues by pLDDT</label>
<div class="e3-trim-actions"><button id="e3ApplyTrim" type="button">Apply residue counts</button>
<button id="e3SuggestTrim" type="button">Suggest from pLDDT</button>
<button id="e3ResetTargetTrim" type="button">Reset this structure</button>
<button id="e3ResetAllTrim" type="button">Reset all structures</button></div>
<canvas id="e3QualityPlot" aria-label="Residue-level pLDDT profile"></canvas>
<p class="note">pLDDT colours: dark blue ≥90; cyan 70–89; yellow 50–69; orange &lt;50.
Low pLDDT is low model confidence and is not proof of biological disorder.</p>
<p id="e3TrimStatus" class="note" aria-live="polite"></p>`;
    const aside = canvasElement.closest(".viewer-layout")?.querySelector("aside")
        || canvasElement.parentElement?.parentElement?.querySelector("aside")
        || document.querySelector("aside");
    if (!aside) return;
    const selectedHeading = Array.from(aside.querySelectorAll("h2,h3"))
        .find(element => element.textContent?.trim() === "Selected residue");
    aside.insertBefore(controls, selectedHeading || null);

    const targetSelect = document.getElementById("e3TrimTarget");
    const nInput = document.getElementById("e3TrimN");
    const cInput = document.getElementById("e3TrimC");
    const thresholdInput = document.getElementById("e3TrimThreshold");
    const minimumRunInput = document.getElementById("e3MinimumRun");
    const qualityToggle = document.getElementById("e3ColourQuality");
    const qualityPlot = document.getElementById("e3QualityPlot");
    const status = document.getElementById("e3TrimStatus");
    const bounds = new Map();
    const pairMode = Boolean(pairPayloadElement);

    function qualityScore(value) {
        if (value === null || value === undefined || value === "") return null;
        const score = Number(value);
        return Number.isFinite(score) ? score : null;
    }
    function qualityColour(score, fallback) {
        const value = qualityScore(score);
        if (value === null) return fallback;
        if (value >= 90) return "#0053d6";
        if (value >= 70) return "#65cbf3";
        if (value >= 50) return "#ffdb13";
        return "#ff7d45";
    }
    function integerValue(element, fallback) {
        const value = Number(element.value);
        return Number.isInteger(value) ? value : fallback;
    }
    function groupKey() {
        return String(document.getElementById("proteinSelect")?.value || "");
    }
    function targetKey() {
        return pairMode ? String(targetSelect.value) : groupKey();
    }
    function atomsFor(key) {
        if (pairMode) return Array.isArray(data[key]) ? data[key] : [];
        const protein = data.proteins.find(item => String(item.accession) === key);
        return Array.isArray(protein?.atoms) ? protein.atoms : [];
    }
    function currentBounds(key) {
        return bounds.get(key) || {n: 0, c: 0};
    }
    function visibleAtoms(atoms, key) {
        const selected = currentBounds(key);
        const start = Math.min(selected.n, Math.max(0, atoms.length - 1));
        const end = Math.max(start + 1, atoms.length - selected.c);
        return atoms.slice(start, end);
    }
    function qualityAvailable(atoms) {
        return atoms.some(atom => qualityScore(atom.plddt) !== null);
    }
    function terminalLowConfidenceRun(atoms, reverse, threshold) {
        let count = 0;
        const ordered = reverse ? [...atoms].reverse() : atoms;
        for (const atom of ordered) {
            const score = qualityScore(atom.plddt);
            if (score === null || score >= threshold) break;
            count += 1;
        }
        return count;
    }
    function renderQualityPlot() {
        const atoms = atomsFor(targetKey());
        const context = qualityPlot.getContext("2d");
        const width = Math.max(260, qualityPlot.getBoundingClientRect().width);
        qualityPlot.width = Math.round(width * devicePixelRatio);
        qualityPlot.height = Math.round(118 * devicePixelRatio);
        context.scale(devicePixelRatio, devicePixelRatio);
        context.clearRect(0, 0, width, 118);
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, 118);
        context.strokeStyle = "#d7e0e6";
        for (const value of [0, 50, 70, 90, 100]) {
            const y = 104 - value;
            context.beginPath();
            context.moveTo(24, y);
            context.lineTo(width - 6, y);
            context.stroke();
        }
        if (!atoms.length || !qualityAvailable(atoms)) {
            context.fillStyle = "#52616d";
            context.font = "12px system-ui";
            context.fillText("Residue-level pLDDT is unavailable in this review bundle.", 30, 58);
            return;
        }
        const selected = currentBounds(targetKey());
        const plotWidth = Math.max(1, width - 32);
        const residueX = index => 24 + plotWidth * index / Math.max(1, atoms.length - 1);
        context.fillStyle = "rgba(80,80,80,.16)";
        if (selected.n) context.fillRect(24, 4, residueX(selected.n) - 24, 100);
        if (selected.c) {
            const start = residueX(Math.max(0, atoms.length - selected.c - 1));
            context.fillRect(start, 4, width - 6 - start, 100);
        }
        const threshold = integerValue(thresholdInput, 70);
        context.strokeStyle = "#9a5c00";
        context.setLineDash([4, 3]);
        context.beginPath();
        context.moveTo(24, 104 - threshold);
        context.lineTo(width - 6, 104 - threshold);
        context.stroke();
        context.setLineDash([]);
        for (let index = 0; index < atoms.length; index += 1) {
            const score = qualityScore(atoms[index].plddt);
            if (score === null) continue;
            context.fillStyle = qualityColour(score, "#607d8b");
            context.fillRect(residueX(index) - 1, 104 - score - 1, 3, 3);
        }
    }
    function syncControls(message) {
        const key = targetKey();
        const atoms = atomsFor(key);
        const selected = currentBounds(key);
        const maximum = Math.max(0, atoms.length - 1);
        nInput.max = String(maximum);
        cInput.max = String(maximum);
        nInput.value = String(selected.n);
        cInput.value = String(selected.c);
        qualityToggle.disabled = !qualityAvailable(atoms);
        document.getElementById("e3SuggestTrim").disabled = !qualityAvailable(atoms);
        status.textContent = message || `${key || "Selected structure"}: ${atoms.length} Cα residues; `
            + `${selected.n} N-terminal and ${selected.c} C-terminal residues hidden.`;
        renderQualityPlot();
    }
    function redraw() {
        draw();
        renderQualityPlot();
    }
    function applyCounts() {
        const key = targetKey();
        const atoms = atomsFor(key);
        const maximum = Math.max(0, atoms.length - 1);
        let nCount = Math.max(0, Math.min(maximum, integerValue(nInput, 0)));
        let cCount = Math.max(0, Math.min(maximum, integerValue(cInput, 0)));
        if (nCount + cCount >= atoms.length && atoms.length) {
            cCount = Math.max(0, atoms.length - nCount - 1);
        }
        bounds.set(key, {n: nCount, c: cCount});
        syncControls(`${key}: applied visual trim; ${nCount} N-terminal and ${cCount} `
            + "C-terminal Cα residues hidden.");
        redraw();
    }
    function suggestCounts() {
        const key = targetKey();
        const atoms = atomsFor(key);
        const threshold = integerValue(thresholdInput, 70);
        const minimum = Math.max(1, integerValue(minimumRunInput, 10));
        let nCount = terminalLowConfidenceRun(atoms, false, threshold);
        let cCount = terminalLowConfidenceRun(atoms, true, threshold);
        nCount = nCount >= minimum ? nCount : 0;
        cCount = cCount >= minimum ? cCount : 0;
        if (nCount + cCount >= atoms.length && atoms.length) {
            nCount = 0;
            cCount = 0;
        }
        bounds.set(key, {n: nCount, c: cCount});
        syncControls(`${key}: suggested ${nCount} N-terminal and ${cCount} C-terminal `
            + `residues below pLDDT ${threshold}. Review before interpretation.`);
        redraw();
    }

    if (pairMode) {
        const labels = {
            reference: `Reference · ${data.metadata?.reference || "structure"}`,
            mobile: `Aligned member · ${data.metadata?.mobile || "structure"}`,
        };
        for (const key of ["reference", "mobile"]) {
            const option = document.createElement("option");
            option.value = key;
            option.textContent = labels[key];
            targetSelect.appendChild(option);
        }
        const originalAllVisible = allVisible;
        const originalTrace = trace;
        const originalPockets = pockets;
        allVisible = function trimmedAllVisible() {
            const selected = [
                ...visibleAtoms(data.reference, "reference"),
                ...visibleAtoms(data.mobile, "mobile"),
            ];
            return selected.length ? selected : originalAllVisible();
        };
        trace = function trimmedTrace(records, kind, colour, show) {
            const selected = visibleAtoms(records, kind);
            if (!qualityToggle.checked || !qualityAvailable(selected)) {
                originalTrace(selected, kind, colour, show);
                return;
            }
            if (!show) return;
            const points = selected.map((atom, index) => project(atom, kind, index));
            ctx.lineWidth = 2 * devicePixelRatio;
            ctx.globalAlpha = .82;
            for (let index = 1; index < points.length; index += 1) {
                ctx.strokeStyle = qualityColour(points[index].atom.plddt, colour);
                ctx.beginPath();
                ctx.moveTo(points[index - 1].x, points[index - 1].y);
                ctx.lineTo(points[index].x, points[index].y);
                ctx.stroke();
            }
            ctx.globalAlpha = 1;
            for (const point of points) {
                ctx.fillStyle = qualityColour(point.atom.plddt, colour);
                ctx.beginPath();
                ctx.arc(point.x, point.y, 2.2 * devicePixelRatio, 0, Math.PI * 2);
                ctx.fill();
            }
            projected.push(...points);
        };
        pockets = function trimmedPockets(records, kind, colour, showStructure) {
            originalPockets(visibleAtoms(records, kind), kind, colour, showStructure);
        };
        targetSelect.addEventListener("change", () => syncControls());
    } else {
        document.getElementById("e3TargetLabel").style.display = "none";
        const originalCurrentProtein = currentProtein;
        const originalDraw = draw;
        currentProtein = function trimmedCurrentProtein() {
            const protein = originalCurrentProtein();
            return {...protein, atoms: visibleAtoms(protein.atoms, String(protein.accession))};
        };
        draw = function qualityAwareGroupDraw() {
            originalDraw();
            if (!qualityToggle.checked) return;
            const points = projected.filter(point => qualityScore(point.atom.plddt) !== null);
            for (const point of points) {
                ctx.fillStyle = qualityColour(point.atom.plddt, "#62aef5");
                ctx.beginPath();
                ctx.arc(point.x, point.y, 2.3 * devicePixelRatio, 0, Math.PI * 2);
                ctx.fill();
            }
        };
        document.getElementById("proteinSelect")?.addEventListener(
            "change", () => syncControls()
        );
    }

    document.getElementById("e3ApplyTrim").addEventListener("click", applyCounts);
    document.getElementById("e3SuggestTrim").addEventListener("click", suggestCounts);
    document.getElementById("e3ResetTargetTrim").addEventListener("click", () => {
        bounds.delete(targetKey());
        syncControls(`${targetKey()}: full model restored.`);
        redraw();
    });
    document.getElementById("e3ResetAllTrim").addEventListener("click", () => {
        bounds.clear();
        syncControls("All structures restored to their complete Cα traces.");
        redraw();
    });
    thresholdInput.addEventListener("input", () => {
        document.getElementById("e3ThresholdValue").value = thresholdInput.value;
        renderQualityPlot();
    });
    qualityToggle.addEventListener("change", redraw);
    window.addEventListener("resize", renderQualityPlot);
    syncControls();
    redraw();
}());
