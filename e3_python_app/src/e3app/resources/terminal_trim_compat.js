"use strict";
(function initialiseE3TerminalTrimming() {
    const canvasElement = document.getElementById("viewer");
    const pairPayloadElement = document.getElementById("alignmentData");
    const groupPayloadElement = document.getElementById("reviewData");
    const trimCore = globalThis.E3TerminalTrimCore;
    if (!canvasElement || (!pairPayloadElement && !groupPayloadElement) || !trimCore) return;
    if (document.getElementById("e3TerminalTrimControls")) return;

    const pairMode = Boolean(pairPayloadElement);
    const aside = canvasElement.closest(".viewer-layout")?.querySelector("aside")
        || canvasElement.closest("main")?.querySelector("aside")
        || document.querySelector("aside");
    if (!aside) return;

    const style = document.createElement("style");
    style.id = "e3TerminalTrimStyle";
    style.textContent = `
#e3TerminalTrimControls{border:1px solid #b9c9d4;border-radius:10px;margin:.9rem 0;
padding:.8rem;background:#f7fafc}#e3TerminalTrimControls h3{margin:.05rem 0 .35rem}
#e3TerminalTrimControls h4{margin:.05rem 0 .35rem;font-size:1rem}
#e3TerminalTrimControls label{display:block;margin:.48rem 0}
#e3TerminalTrimControls input[type=number],#e3TerminalTrimControls select{
width:100%;padding:.42rem;margin-top:.2rem}#e3TerminalTrimControls input[type=range]{width:100%}
#e3TerminalTrimControls button{width:100%;padding:.55rem;margin:.15rem 0;cursor:pointer}
#e3TerminalTrimControls button:disabled{cursor:not-allowed;opacity:.58}
#e3TerminalTrimControls button.e3-primary{background:#0b5f8a;color:#fff;border:1px solid #084a6c;
border-radius:5px;font-weight:700}#e3TerminalTrimControls .e3-trim-grid,
#e3TerminalTrimControls .e3-trim-actions{display:grid;grid-template-columns:1fr 1fr;gap:.45rem}
#e3TerminalTrimControls .e3-method{border:1px solid #d1dde4;border-radius:8px;background:#fff;
padding:.65rem;margin:.7rem 0}#e3TerminalTrimControls details.e3-method>summary{cursor:pointer;
font-weight:700}#e3TerminalTrimControls details.e3-method[open]>summary{margin-bottom:.5rem}
#e3TerminalTrimControls .e3-current{border-left:5px solid #0b5f8a;background:#eaf5fa;
padding:.55rem .65rem;margin:.65rem 0;border-radius:4px;line-height:1.45}
#e3TerminalTrimControls .e3-suggestion{background:#f0f7fb;border-radius:5px;padding:.5rem;
margin:.45rem 0;line-height:1.4}#e3TerminalTrimControls .e3-unavailable{background:#fff5d9}
#e3TerminalTrimControls .e3-advanced{margin-top:.55rem}
#e3TerminalTrimControls .e3-advanced>summary{cursor:pointer;font-weight:600;color:#31576d}
#e3TerminalTrimControls .e3-visual-only{display:inline-block;border-radius:999px;
background:#dcecf4;color:#18475f;padding:.08rem .45rem;font-size:.76rem;vertical-align:.14rem}
#e3QualityPanel{border:1px solid #b9c9d4;border-radius:10px;margin:1rem 0;padding:1rem;
background:#f7fafc;min-width:0}body>#e3QualityPanel{margin:0 1rem 1rem}
#e3QualityPanel h2,#e3QualityPanel h3{margin:.05rem 0 .25rem}
#e3QualityMetrics{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:.55rem;
margin:.8rem 0}#e3QualityMetrics div{background:#fff;border:1px solid #d1dde4;border-radius:7px;
padding:.55rem}#e3QualityMetrics strong{display:block;font-size:1.08rem;color:#173f5f;
overflow-wrap:anywhere}#e3QualityMetrics span{font-size:.78rem;color:#52616d}
#e3QualityPlotShell{position:relative;overflow-x:auto;background:#fff;border:1px solid #b7c8d2;
border-radius:7px;padding:.25rem}#e3QualityPlot{display:block;width:100%;min-width:920px;height:390px;
background:#fff}#e3QualityEmpty{background:#fff5d9;border:1px solid #e1c66d;border-radius:7px;
padding:1rem;margin-top:.7rem;line-height:1.45}#e3QualityTooltip{position:absolute;display:none;
pointer-events:none;background:#132a3a;color:#fff;border-radius:5px;padding:.35rem .5rem;
font-size:.8rem;white-space:nowrap;z-index:3;box-shadow:0 2px 8px #0004}
#e3QualityLegend{display:flex;flex-wrap:wrap;gap:.4rem 1rem;margin:.6rem 0 .15rem;
font-size:.85rem}#e3QualityLegend span::before{content:"";display:inline-block;width:.75rem;
height:.75rem;border-radius:2px;margin-right:.3rem;vertical-align:-.08rem}
#e3QualityLegend .e3-very-high::before{background:#0053d6}.e3-confident::before{background:#65cbf3}
#e3QualityLegend .e3-low::before{background:#ffdb13}.e3-very-low::before{background:#ff7d45}
#e3TrimStatus{min-height:2.5rem;margin-bottom:.1rem}
@media(max-width:900px){#e3QualityMetrics{grid-template-columns:1fr 1fr}
#e3TerminalTrimControls .e3-trim-grid,#e3TerminalTrimControls .e3-trim-actions{
grid-template-columns:1fr}}
@media(max-width:560px){#e3QualityMetrics{grid-template-columns:1fr}}
`;
    document.head.appendChild(style);

    const controls = document.createElement("section");
    controls.id = "e3TerminalTrimControls";
    controls.setAttribute("aria-label", "Terminal display controls");
    controls.innerHTML = `
<h3>Hide terminal regions <span class="e3-visual-only">visual preview only</span></h3>
<p class="note">Choose a structure, review the AlphaFold suggestion, then apply it. The
source model, alignment, pockets, scores and ranking never change.</p>
<label id="e3TargetLabel"><strong>Structure to review</strong>
<select id="e3TrimTarget"></select></label>
<div id="e3TrimSummary" class="e3-current" aria-live="polite"></div>
<section id="e3AutomaticPanel" class="e3-method">
<h4>Recommended low-confidence trim</h4>
<div id="e3SuggestionSummary" class="e3-suggestion" aria-live="polite"></div>
<div class="e3-trim-actions">
<button id="e3ApplySuggested" class="e3-primary" type="button">
Apply recommendation</button>
<button id="e3ApplyBothSuggested" type="button">Apply to both structures</button>
</div>
<details class="e3-advanced"><summary>Adjust recommendation sensitivity</summary>
<label>Low-confidence boundary: pLDDT below <output id="e3ThresholdValue">70</output>
<input id="e3TrimThreshold" type="range" min="0" max="100" step="1" value="70"></label>
<label>Minimum continuous terminal region (residues)
<input id="e3MinimumRun" type="number" min="1" step="1" value="10"></label>
<p class="note">Only a continuous run from the first or last modelled residue is suggested.
Missing confidence is never treated as low confidence.</p></details></section>
<details id="e3ManualPanel" class="e3-method"><summary>Manual fine-tuning (optional)</summary>
<p class="note">Use this when confidence is unavailable or when you want different boundaries.</p>
<div class="e3-trim-grid">
<label>Hide from N terminus (residues)
<input id="e3TrimN" type="number" min="0" step="1" value="0"></label>
<label>Hide from C terminus (residues)
<input id="e3TrimC" type="number" min="0" step="1" value="0"></label>
</div><button id="e3ApplyManual" type="button">Apply manual values</button></details>
<label><input id="e3ColourQuality" type="checkbox" checked>
Colour the 3D trace by AlphaFold confidence</label>
<div class="e3-trim-actions"><button id="e3ResetTargetTrim" type="button">
Restore selected structure</button><button id="e3ResetAllTrim" type="button">
Restore all structures</button></div>
<p id="e3TrimStatus" class="note" aria-live="polite"></p>`;
    const selectedHeading = Array.from(aside.querySelectorAll("h2,h3"))
        .find(element => element.textContent?.trim() === "Selected residue");
    aside.insertBefore(controls, selectedHeading || null);

    const qualityPanel = document.createElement("section");
    qualityPanel.id = "e3QualityPanel";
    qualityPanel.setAttribute("aria-label", "Residue-level AlphaFold confidence");
    qualityPanel.innerHTML = `
<h2>AlphaFold confidence along the sequence</h2>
<p class="note">Use this full-width profile to review the terminal recommendation. Grey regions
are currently hidden; blue-tinted regions are suggested but not yet applied.</p>
<div id="e3QualityMetrics">
<div><strong id="e3QualityStructure">—</strong><span>selected structure</span></div>
<div><strong id="e3QualityCoverage">—</strong><span>residues with pLDDT</span></div>
<div><strong id="e3QualityMean">—</strong><span>mean available pLDDT</span></div>
<div><strong id="e3QualityVisible">—</strong><span>residues currently visible</span></div>
</div>
<div id="e3QualityEmpty" hidden><strong>Confidence profile not loaded.</strong><br>
Use “Load AlphaFold confidence for graph and trimming” above this viewer. Manual terminal
display controls remain available.</div>
<div id="e3QualityPlotShell"><canvas id="e3QualityPlot" role="img"
aria-label="Residue-level pLDDT profile"></canvas><div id="e3QualityTooltip"></div></div>
<div id="e3QualityLegend"><span class="e3-very-high">Very high ≥90</span>
<span class="e3-confident">Confident 70–89</span><span class="e3-low">Low 50–69</span>
<span class="e3-very-low">Very low &lt;50</span></div>
<p class="note">Low pLDDT means low local model confidence; by itself, it does not prove
biological disorder.</p>`;
    const groupViewerLayout = canvasElement.closest(".viewer-layout");
    const pairViewerMain = canvasElement.closest("main");
    if (groupViewerLayout) {
        groupViewerLayout.insertAdjacentElement("afterend", qualityPanel);
    } else if (pairViewerMain) {
        pairViewerMain.insertAdjacentElement("afterend", qualityPanel);
    } else {
        canvasElement.parentElement?.insertAdjacentElement("afterend", qualityPanel);
    }

    const targetSelect = document.getElementById("e3TrimTarget");
    const nInput = document.getElementById("e3TrimN");
    const cInput = document.getElementById("e3TrimC");
    const thresholdInput = document.getElementById("e3TrimThreshold");
    const minimumRunInput = document.getElementById("e3MinimumRun");
    const qualityToggle = document.getElementById("e3ColourQuality");
    const qualityPlot = document.getElementById("e3QualityPlot");
    const qualityPlotShell = document.getElementById("e3QualityPlotShell");
    const qualityTooltip = document.getElementById("e3QualityTooltip");
    const qualityEmpty = document.getElementById("e3QualityEmpty");
    const status = document.getElementById("e3TrimStatus");
    const boundsByStructure = new Map();
    let lastPlotGeometry = null;

    /** Return the current group accession. */
    function groupKey() {
        return String(document.getElementById("proteinSelect")?.value || "");
    }

    /** Return the stable key for the structure controlled by the panel. */
    function targetKey() {
        return pairMode ? String(targetSelect.value) : groupKey();
    }

    /** Return a readable label for the selected structure. */
    function targetLabel() {
        if (pairMode) return targetSelect.selectedOptions[0]?.textContent || targetKey();
        return targetKey() || "Selected structure";
    }

    /** Return ordered C-alpha records for a structure key. */
    function atomsFor(key) {
        if (pairMode) return Array.isArray(data[key]) ? data[key] : [];
        const proteins = Array.isArray(data.proteins) ? data.proteins : [];
        const protein = proteins.find(item => String(item.accession) === key);
        return Array.isArray(protein?.atoms) ? protein.atoms : [];
    }

    /** Return the applied display bounds for a structure key. */
    function currentBounds(key) {
        return boundsByStructure.get(key) || {n: 0, c: 0};
    }

    /** Return only atoms inside the applied reversible display bounds. */
    function visibleAtoms(atoms, key) {
        const selected = currentBounds(key);
        const start = Math.min(selected.n, Math.max(0, atoms.length - 1));
        const end = Math.max(start + 1, atoms.length - selected.c);
        return atoms.slice(start, end);
    }

    /** Return the current confidence-based recommendation for a structure. */
    function recommendationFor(key) {
        return trimCore.suggestedTrim(
            atomsFor(key), thresholdInput.value, minimumRunInput.value,
        );
    }

    /** Return an AlphaFold-compatible colour for a validated score. */
    function qualityColour(score, fallback) {
        const value = trimCore.qualityScore(score);
        if (value === null) return fallback;
        if (value >= 90) return "#0053d6";
        if (value >= 70) return "#36a9d6";
        if (value >= 50) return "#e0ad00";
        return "#ee6138";
    }

    /** Draw a filled pLDDT background band. */
    function drawQualityBand(context, geometry, lower, upper, colour) {
        const yUpper = geometry.bottom - geometry.height * upper / 100;
        const yLower = geometry.bottom - geometry.height * lower / 100;
        context.fillStyle = colour;
        context.fillRect(geometry.left, yUpper, geometry.width, yLower - yUpper);
    }

    /** Draw applied or proposed terminal regions on the confidence graph. */
    function drawTerminalRegion(context, geometry, start, end, label, colour) {
        if (end <= start) return;
        const startX = geometry.x(start);
        const endX = geometry.x(end);
        context.fillStyle = colour;
        context.fillRect(startX, geometry.top, endX - startX, geometry.height);
        if (endX - startX > 52) {
            context.save();
            context.fillStyle = "#253946";
            context.font = "600 12px system-ui";
            context.textAlign = "center";
            context.textBaseline = "top";
            context.fillText(label, startX + (endX - startX) / 2, geometry.top + 6);
            context.restore();
        }
    }

    /** Update graph summary cards using explicit available and missing data. */
    function updateQualityMetrics(atoms, summary, selected) {
        document.getElementById("e3QualityStructure").textContent = targetLabel();
        document.getElementById("e3QualityCoverage").textContent = summary.total
            ? `${summary.available} / ${summary.total}` : "0 / 0";
        document.getElementById("e3QualityMean").textContent = summary.mean === null
            ? "Unavailable" : summary.mean.toFixed(1);
        document.getElementById("e3QualityVisible").textContent = String(
            Math.max(0, atoms.length - selected.n - selected.c),
        );
    }

    /** Render the large residue-level confidence graph. */
    function renderQualityPlot() {
        const key = targetKey();
        const atoms = atomsFor(key);
        const selected = currentBounds(key);
        const summary = trimCore.confidenceSummary(atoms);
        const suggestion = recommendationFor(key);
        updateQualityMetrics(atoms, summary, selected);
        const available = summary.available > 0;
        qualityEmpty.hidden = available;
        qualityPlotShell.hidden = !available;
        document.getElementById("e3QualityLegend").hidden = !available;
        if (!available) {
            lastPlotGeometry = null;
            return;
        }

        const context = qualityPlot.getContext("2d");
        const width = Math.max(920, qualityPlot.getBoundingClientRect().width);
        const height = 390;
        const pixelRatio = window.devicePixelRatio || 1;
        const left = 68;
        const right = width - 32;
        const top = 26;
        const bottom = 320;
        const plotWidth = Math.max(1, right - left);
        const plotHeight = bottom - top;
        const residueX = index => left
            + plotWidth * index / Math.max(1, atoms.length - 1);
        const geometry = {
            left, right, top, bottom, width: plotWidth, height: plotHeight, x: residueX,
        };
        lastPlotGeometry = {geometry, atoms, cssWidth: width};
        qualityPlot.width = Math.round(width * pixelRatio);
        qualityPlot.height = Math.round(height * pixelRatio);
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        context.clearRect(0, 0, width, height);
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, height);
        drawQualityBand(context, geometry, 90, 100, "rgba(0,83,214,.08)");
        drawQualityBand(context, geometry, 70, 90, "rgba(54,169,214,.10)");
        drawQualityBand(context, geometry, 50, 70, "rgba(255,219,19,.13)");
        drawQualityBand(context, geometry, 0, 50, "rgba(255,125,69,.10)");

        context.font = "13px system-ui";
        context.textAlign = "right";
        context.textBaseline = "middle";
        context.lineWidth = 1;
        for (const value of [0, 50, 70, 90, 100]) {
            const y = bottom - plotHeight * value / 100;
            context.strokeStyle = "#c7d3da";
            context.beginPath();
            context.moveTo(left, y);
            context.lineTo(right, y);
            context.stroke();
            context.fillStyle = "#40535f";
            context.fillText(String(value), left - 10, y);
        }

        const threshold = suggestion.threshold;
        const thresholdY = bottom - plotHeight * threshold / 100;
        context.strokeStyle = "#7a4b00";
        context.lineWidth = 1.5;
        context.setLineDash([6, 4]);
        context.beginPath();
        context.moveTo(left, thresholdY);
        context.lineTo(right, thresholdY);
        context.stroke();
        context.setLineDash([]);
        context.fillStyle = "#6d4300";
        context.textAlign = "left";
        context.fillText(`suggestion boundary ${threshold}`, left + 7, thresholdY - 10);

        const appliedEnd = Math.max(0, atoms.length - selected.c - 1);
        drawTerminalRegion(
            context, geometry, 0, selected.n, "hidden", "rgba(65,72,77,.28)",
        );
        drawTerminalRegion(
            context, geometry, appliedEnd, atoms.length - 1,
            "hidden", "rgba(65,72,77,.28)",
        );
        if (selected.n !== suggestion.n || selected.c !== suggestion.c) {
            drawTerminalRegion(
                context, geometry, 0, suggestion.n, "suggested", "rgba(11,95,138,.13)",
            );
            const suggestedEnd = Math.max(0, atoms.length - suggestion.c - 1);
            drawTerminalRegion(
                context, geometry, suggestedEnd, atoms.length - 1,
                "suggested", "rgba(11,95,138,.13)",
            );
        }

        let previous = null;
        for (let index = 0; index < atoms.length; index += 1) {
            const score = trimCore.qualityScore(atoms[index].plddt);
            if (score === null) {
                previous = null;
                continue;
            }
            const point = {
                x: residueX(index),
                y: bottom - plotHeight * score / 100,
                score,
            };
            if (previous !== null) {
                context.strokeStyle = qualityColour((previous.score + score) / 2, "#52616d");
                context.lineWidth = 2.6;
                context.beginPath();
                context.moveTo(previous.x, previous.y);
                context.lineTo(point.x, point.y);
                context.stroke();
            }
            previous = point;
        }
        const pointStep = Math.max(1, Math.ceil(atoms.length / Math.max(1, plotWidth / 5)));
        for (let index = 0; index < atoms.length; index += pointStep) {
            const score = trimCore.qualityScore(atoms[index].plddt);
            if (score === null) continue;
            const y = bottom - plotHeight * score / 100;
            context.fillStyle = qualityColour(score, "#52616d");
            context.beginPath();
            context.arc(residueX(index), y, 2.6, 0, Math.PI * 2);
            context.fill();
        }

        context.fillStyle = "#40535f";
        context.textAlign = "center";
        context.textBaseline = "top";
        const tickCount = Math.min(10, Math.max(2, Math.floor(width / 145)));
        for (let tick = 0; tick <= tickCount; tick += 1) {
            const index = Math.round((atoms.length - 1) * tick / tickCount);
            context.fillText(
                String(atoms[index].resi || index + 1), residueX(index), bottom + 9,
            );
        }
        context.save();
        context.translate(19, top + plotHeight / 2);
        context.rotate(-Math.PI / 2);
        context.font = "600 13px system-ui";
        context.fillText("AlphaFold confidence (pLDDT)", 0, 0);
        context.restore();
        context.font = "600 13px system-ui";
        context.fillText("Structure residue", left + plotWidth / 2, bottom + 35);
        qualityPlot.setAttribute(
            "aria-label",
            `${targetLabel()} pLDDT profile for ${summary.available} of ${summary.total} residues`,
        );
    }

    /** Update all controls and summaries for the selected structure. */
    function syncControls(message) {
        const key = targetKey();
        const atoms = atomsFor(key);
        const selected = currentBounds(key);
        const summary = trimCore.confidenceSummary(atoms);
        const suggestion = recommendationFor(key);
        const maximum = Math.max(0, atoms.length - 1);
        nInput.max = String(maximum);
        cInput.max = String(maximum);
        nInput.value = String(selected.n);
        cInput.value = String(selected.c);
        document.getElementById("e3TrimSummary").textContent = atoms.length
            ? `${targetLabel()}: ${atoms.length - selected.n - selected.c} of ${atoms.length} `
                + `residues visible (${selected.n} hidden at N terminus; ${selected.c} at C terminus).`
            : `${targetLabel()}: no Cα trace is available.`;
        const suggestionSummary = document.getElementById("e3SuggestionSummary");
        if (suggestion.available) {
            suggestionSummary.classList.remove("e3-unavailable");
            suggestionSummary.textContent = suggestion.n || suggestion.c
                ? `Suggested: hide ${suggestion.n} N-terminal and ${suggestion.c} C-terminal `
                    + `residues (continuous pLDDT < ${suggestion.threshold}).`
                : `No sustained low-confidence terminal region meets the current criteria.`;
        } else {
            suggestionSummary.classList.add("e3-unavailable");
            suggestionSummary.textContent = "No residue-level pLDDT is loaded for this structure. "
                + "Use manual fine-tuning or load AlphaFold confidence above the viewer.";
        }
        document.getElementById("e3ApplySuggested").disabled = !suggestion.available;
        document.getElementById("e3ApplyBothSuggested").disabled = !pairMode
            || !["reference", "mobile"].some(role => recommendationFor(role).available);
        document.getElementById("e3ApplyBothSuggested").hidden = !pairMode;
        qualityToggle.disabled = summary.available === 0;
        if (summary.available === 0) {
            qualityToggle.checked = false;
        } else if (!qualityToggle.dataset.userTouched) {
            qualityToggle.checked = true;
        }
        status.textContent = message || "Review the suggestion before applying it. "
            + "All changes are reversible and affect this display only.";
        renderQualityPlot();
    }

    /** Redraw the structure and confidence profile. */
    function redraw() {
        draw();
        renderQualityPlot();
    }

    /** Apply validated manual counts to the selected structure. */
    function applyManualCounts() {
        const key = targetKey();
        const atoms = atomsFor(key);
        const selected = trimCore.clampCounts(nInput.value, cInput.value, atoms.length);
        boundsByStructure.set(key, {n: selected.n, c: selected.c});
        const adjustment = selected.adjusted
            ? " Values were bounded to retain at least one residue." : "";
        syncControls(
            `${targetLabel()}: manual display applied.${adjustment}`,
        );
        redraw();
    }

    /** Apply the current confidence recommendation to one structure. */
    function applySuggestion(key) {
        const suggestion = recommendationFor(key);
        if (!suggestion.available) return false;
        boundsByStructure.set(key, {n: suggestion.n, c: suggestion.c});
        return true;
    }

    /** Apply the current recommendation to the selected structure. */
    function applySelectedSuggestion() {
        const key = targetKey();
        if (!applySuggestion(key)) {
            syncControls(`${targetLabel()}: confidence is unavailable; nothing was changed.`);
            return;
        }
        const selected = currentBounds(key);
        syncControls(
            `${targetLabel()}: recommendation applied; ${selected.n} N-terminal and `
            + `${selected.c} C-terminal residues hidden.`,
        );
        redraw();
    }

    /** Apply independent confidence recommendations to both pair structures. */
    function applyBothSuggestions() {
        const applied = ["reference", "mobile"].filter(applySuggestion);
        syncControls(
            applied.length
                ? `Applied independent recommendations to ${applied.length} structure(s).`
                : "Confidence is unavailable for both structures; nothing was changed.",
        );
        redraw();
    }

    /** Show exact residue confidence under the graph pointer. */
    function showQualityTooltip(event) {
        if (!lastPlotGeometry) return;
        const {geometry, atoms, cssWidth} = lastPlotGeometry;
        const rectangle = qualityPlot.getBoundingClientRect();
        const x = (event.clientX - rectangle.left) * cssWidth / rectangle.width;
        if (x < geometry.left || x > geometry.right) {
            qualityTooltip.style.display = "none";
            return;
        }
        const index = Math.max(0, Math.min(
            atoms.length - 1,
            Math.round((x - geometry.left) * (atoms.length - 1) / geometry.width),
        ));
        const score = trimCore.qualityScore(atoms[index].plddt);
        const residue = String(atoms[index].resi || index + 1);
        qualityTooltip.textContent = score === null
            ? `Residue ${residue}: pLDDT unavailable`
            : `Residue ${residue}: pLDDT ${score.toFixed(1)}`;
        qualityTooltip.style.left = `${Math.min(rectangle.width - 170, event.offsetX + 14)}px`;
        qualityTooltip.style.top = `${Math.max(8, event.offsetY - 32)}px`;
        qualityTooltip.style.display = "block";
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
            if (!qualityToggle.checked
                    || !trimCore.confidenceSummary(selected).available) {
                originalTrace(selected, kind, colour, show);
                return;
            }
            if (!show) return;
            const points = selected.map((atom, index) => project(atom, kind, index));
            ctx.lineWidth = 2.4 * devicePixelRatio;
            ctx.globalAlpha = .88;
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
                ctx.arc(point.x, point.y, 2.4 * devicePixelRatio, 0, Math.PI * 2);
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
            const points = projected.filter(
                point => trimCore.qualityScore(point.atom.plddt) !== null,
            );
            for (const point of points) {
                ctx.fillStyle = qualityColour(point.atom.plddt, "#62aef5");
                ctx.beginPath();
                ctx.arc(point.x, point.y, 2.5 * devicePixelRatio, 0, Math.PI * 2);
                ctx.fill();
            }
        };
        document.getElementById("proteinSelect")?.addEventListener(
            "change", () => syncControls(),
        );
    }

    document.getElementById("e3ApplyManual").addEventListener("click", applyManualCounts);
    document.getElementById("e3ApplySuggested").addEventListener(
        "click", applySelectedSuggestion,
    );
    document.getElementById("e3ApplyBothSuggested").addEventListener(
        "click", applyBothSuggestions,
    );
    document.getElementById("e3ResetTargetTrim").addEventListener("click", () => {
        boundsByStructure.delete(targetKey());
        syncControls(`${targetLabel()}: complete trace restored.`);
        redraw();
    });
    document.getElementById("e3ResetAllTrim").addEventListener("click", () => {
        boundsByStructure.clear();
        syncControls("All structures restored to their complete Cα traces.");
        redraw();
    });
    thresholdInput.addEventListener("input", () => {
        document.getElementById("e3ThresholdValue").value = thresholdInput.value;
        syncControls("Recommendation updated but not applied.");
    });
    minimumRunInput.addEventListener("change", () => {
        minimumRunInput.value = String(Math.max(
            1, trimCore.integerValue(minimumRunInput.value, 10),
        ));
        syncControls("Recommendation updated but not applied.");
    });
    qualityToggle.addEventListener("change", () => {
        qualityToggle.dataset.userTouched = "true";
        redraw();
    });
    qualityPlot.addEventListener("mousemove", showQualityTooltip);
    qualityPlot.addEventListener("mouseleave", () => {
        qualityTooltip.style.display = "none";
    });
    window.addEventListener("resize", renderQualityPlot);
    syncControls();
    redraw();
}());
