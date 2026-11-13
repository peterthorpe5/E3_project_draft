/* global draw, projected, canvas, ctx, currentProtein, colours, palette, selectedRank */
import { mountSequenceSearch, rangePositions } from "./sequence-search.js";
import "../src/e3app/resources/viewer_pdf.js";

const payload = document.getElementById("e3ReviewHighlights");
const trim = document.getElementById("e3TerminalTrimControls");
if (payload && trim && typeof draw === "function" && typeof canvas !== "undefined") {
  mountReviewHighlights();
}

/** Extend the existing projection so highlights follow its rotation, zoom and trimming. */
function mountReviewHighlights() {
  const { group, targets } = JSON.parse(payload.textContent);
  const pair = Boolean(document.getElementById("alignmentData"));
  const domainDefault = "#c1a8ff";
  const originalDraw = draw;
  let domains = [];
  let matches = new Set();
  let domainPositions = new Set();
  let matchSelection;

  const panel = document.createElement("section");
  panel.className = "e3-review-highlights";
  panel.setAttribute("aria-label", "Highlight domains and sequence matches");
  panel.innerHTML = `
    <style>
      .e3-review-highlights{padding:.7rem;border:1px solid #b9c9d4;border-radius:8px;
        margin:.75rem 0;background:#f7fafc}
      .e3-review-highlights h3{margin:0 0 .5rem}
      .e3-review-highlights label{display:block;margin:.3rem 0}
      .e3-review-highlights select,.e3-review-highlights input[type=text]{max-width:100%}
      .e3-review-highlights .sequence-search{border-top:1px solid #d7dee5;margin-top:.5rem;
        padding-top:.3rem}
      .e3-review-highlights .sequence-search p:empty,.e3-review-highlights [hidden]{display:none}
      .e3-review-highlights input[type=number]{width:5em}
      .e3-review-highlights .trace-colour-picker{display:flex;align-items:center;gap:.4rem}
    </style>
    <h3>Highlight residues</h3>
    <label class="e3-highlight-target" hidden>Structure to highlight
      <select aria-label="Structure to highlight"><option value="reference">Reference</option><option value="mobile">Aligned member</option></select>
    </label>
    <label>Protein domain <select class="e3-domain" aria-label="Protein domain"></select></label>
    <label class="trace-colour-picker">Domain colour <input type="color" value="${domainDefault}"></label>
    <p class="e3-domain-source" aria-live="polite"></p>`;
  trim.before(panel);
  const target = panel.querySelector(".e3-highlight-target select");
  target.parentElement.hidden = !pair;
  const domain = panel.querySelector(".e3-domain");
  const domainColour = panel.querySelector('input[type="color"]');
  const domainSource = panel.querySelector(".e3-domain-source");
  const search = mountSequenceSearch(panel, selection => {
    matchSelection = selection;
    matches = rangePositions(selection.ranges);
    draw();
  });

  function targetKey() {
    return pair ? target.value : currentProtein().accession;
  }

  function selectDomain() {
    const feature = domains[domain.value];
    domainPositions = feature
      ? rangePositions(feature.locations.flatMap(location => location.fragments)) : new Set();
    domainColour.disabled = !feature;
    domainSource.textContent = feature?.provenance === "recorded_coordinates"
      ? "Recorded accession and length match. The domain overlay is approximate."
      : !domains.length ? "Recorded domains are unavailable for this structure." : "";
    draw();
  }

  function selectTarget() {
    const model = targets[targetKey()];
    domains = model?.features || [];
    domain.replaceChildren(new Option("No domain selected", ""));
    for (const [index, feature] of domains.entries()) {
      const coordinates = feature.locations.flatMap(location => location.fragments)
        .map(({ start, end }) => start === end ? start : `${start}–${end}`).join(", ");
      const label = [feature.accession, feature.description, coordinates].filter(Boolean).join(" · ");
      domain.appendChild(new Option(label, String(index)));
    }
    domain.disabled = !domains.length;
    selectDomain();
    search.setSequence(model?.sequence);
  }

  function ring(point, radius, colour, dashed = false) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius * devicePixelRatio, 0, 2 * Math.PI);
    ctx.strokeStyle = "#131c2b";
    ctx.lineWidth = 4 * devicePixelRatio;
    ctx.stroke();
    ctx.strokeStyle = colour;
    ctx.lineWidth = 2.3 * devicePixelRatio;
    if (dashed) ctx.setLineDash([4 * devicePixelRatio, 2 * devicePixelRatio]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  draw = function highlightedReviewDraw() {
    originalDraw();
    let domainCount = 0, matchCount = 0;
    if (domainPositions.size || matches.size) {
      const role = targetKey();
      const seen = new Set();
      ctx.save();
      for (const point of projected) {
        if (pair && point.kind !== role) continue;
        const position = Number(point.atom.resi);
        if (seen.has(position)) continue;
        seen.add(position);
        if (domainPositions.has(position)) {
          ring(point, 8.9, domainColour.value, true);
          domainCount += 1;
        }
        if (matches.has(position)) {
          ring(point, domainPositions.has(position) ? 12 : 8.9, matchSelection.colour);
          matchCount += 1;
        }
      }
      ctx.restore();
    }
    canvas.dataset.domainCount = String(domainCount);
    canvas.dataset.sequenceCount = String(matchCount);
  };

  const source = pair ? "Pairwise superposition" : "Published pocket-review model";
  const download = document.getElementById("downloadViewPdf") || document.createElement("button");
  if (!download.parentElement) {
    download.type = "button";
    download.textContent = "Download 3D view (PDF)";
    panel.appendChild(download);
  }
  download.onclick = () => {
    const { canvasPdf, downloadBlob, safePdfName } = globalThis.E3ViewerPdf;
    const legend = [];
    const feature = domains[domain.value];
    if (feature) legend.push({
      colour: domainColour.value, label: `Domain: ${domain.selectedOptions[0].textContent}`,
    });
    if (matches.size) legend.push({
      colour: matchSelection.colour, label: `Matches: ${matchSelection.query} · ${matchSelection.summary}`,
    });
    if (pair && typeof colours !== "undefined") {
      for (const role of ["reference", "mobile"]) {
        const label = role === "reference" ? "Reference" : "Aligned member";
        if (document.getElementById(role === "reference" ? "showReference" : "showMobile").checked) {
          if (document.getElementById("showPocket").checked) {
            legend.push({ colour: colours[role + "Pocket"], label: `${label} pocket` });
          }
        }
      }
    } else if (!pair && typeof palette !== "undefined") {
      const rank = selectedRank();
      const visibleRanks = new Set(projected.flatMap(point =>
        (point.atom.pockets || []).map(pocket => pocket.selection_rank)
          .filter(value => !rank || value === rank)));
      for (const value of [...visibleRanks].sort((a, b) => a - b)) {
        legend.push({ colour: palette[value] || "#ffffff", label: `Pocket rank ${value}` });
      }
    }
    const caption = `${source} · ${targetKey()}`;
    downloadBlob(canvasPdf({
      canvas, title: group, subtitle: caption, legend,
      background: getComputedStyle(canvas).backgroundColor,
    }), `${safePdfName(group + "_" + targetKey())}_3d_view.pdf`);
  };

  target.addEventListener("change", selectTarget);
  domain.addEventListener("change", selectDomain);
  domainColour.addEventListener("input", draw);
  document.getElementById("proteinSelect")?.addEventListener("change", selectTarget);
  if (pair) {
    for (const id of ["showReference", "showMobile", "showPocket"]) {
      const toggle = document.getElementById(id);
      if (toggle) toggle.onchange = () => draw();
    }
  }
  selectTarget();
}
