/** Display clickable domains and exact model evidence using Nightingale. */
import Sequence from "@nightingale-elements/nightingale-sequence";
import Navigation from "@nightingale-elements/nightingale-navigation";
import Track from "@nightingale-elements/nightingale-track";
import Linegraph from "@nightingale-elements/nightingale-linegraph-track";
import {
  CONFIDENCE_BANDS, HIGHLIGHT_COLOURS, NEUTRAL_TRACE_COLOUR, mountStructureTrace,
} from "./structure-trace.js";
import { mountSequenceSearch, rangePositions } from "./sequence-search.js";
import "../src/e3app/resources/viewer_pdf.js";

const components = {
  sequence: Sequence, navigation: Navigation, track: Track, "linegraph-track": Linegraph,
};
for (const [name, component] of Object.entries(components)) {
  const tag = "nightingale-" + name;
  if (!customElements.get(tag)) customElements.define(tag, component);
}

const data = JSON.parse(document.getElementById("protein-data").textContent);
const container = document.getElementById("viewer");
const status = document.getElementById("status");
const length = data.sequence ? data.sequence.length : data.length;
if (!Number.isInteger(length) || length < 1) throw new Error("Missing protein coordinate length");
const model = new Map((data.model || []).map(residue => [residue.position, residue]));
const confidenceValues = [...model.values()].map(residue => residue.plddt).filter(Number.isFinite);
const hasConfidence = confidenceValues.length > 0;
const pockets = data.pockets || [];
const trackElements = [];
const active = new Map();
const colourInputs = new Map();
let trace = null;
let resetColours = null;
let sequenceSearch = null;
let sequenceSearchLabel = "";
let displayStart = 1, displayEnd = length;
const scope = data.coordinate_scope || "Exact sequence coordinates";
status.textContent = "Nightingale · " + length + " residues · " + scope;
container.classList.add("protein-feature-viewer");

function element(tag, parent, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  parent.appendChild(node);
  return node;
}

function button(parent, label, action, className) {
  const control = element("button", parent, className, label);
  control.type = "button";
  control.addEventListener("click", action);
  return control;
}

function addTrack(name, parent, height) {
  const track = document.createElement("nightingale-" + name);
  track.setAttribute("length", String(length));
  track.setAttribute("display-start", String(displayStart));
  track.setAttribute("display-end", String(displayEnd));
  track.setAttribute("height", String(height));
  track.setAttribute("highlight-color", HIGHLIGHT_COLOURS.residue);
  parent.appendChild(track);
  trackElements.push(track);
  return track;
}

const prompt = model.size ? "Select a domain, pocket or residue." : "Select a feature.";
const selection = element("div", container, "feature-selection");
const detail = element("p", selection, "feature-selection-detail", prompt);
detail.setAttribute("aria-live", "polite");
const clear = button(selection, "Clear selection", () => {
  for (const item of active.values()) item.control?.setAttribute("aria-pressed", "false");
  active.clear();
  if (sequenceSearch) sequenceSearch.clear();
  else updateSelection();
});
clear.disabled = true;

function updateWindow(start, end) {
  displayStart = Math.max(1, Math.min(length, Math.floor(start)));
  displayEnd = Math.min(length, Math.max(displayStart, Math.ceil(end)));
  for (const track of trackElements) {
    track.setAttribute("display-start", String(displayStart));
    track.setAttribute("display-end", String(displayEnd));
  }
}

function updateSelection() {
  for (const track of trackElements) {
    const kind = track.selection?.kind;
    const item = kind ? active.get(kind) : active.get("residue");
    const selected = item && (!kind || track.selection === item);
    if (selected) track.setAttribute("highlight", item.ranges.map(({ start, end }) => `${start}:${end}`).join(","));
    else track.removeAttribute("highlight");
  }
  const highlights = {};
  const labels = [];
  for (const [kind, { ranges, label, colour }] of active) {
    const positions = model.size
      ? [...rangePositions(ranges)].filter(position => model.has(position)) : [];
    highlights[kind] = { positions, colour };
    if (kind === "sequence") {
      labels.push(`Sequence matches · ${positions.length} model residues`);
      continue;
    }
    const coordinates = ranges.slice(0, 12).map(({ start, end }) =>
      start === end ? String(start) : start + "–" + end).join(", ");
    const shown = coordinates + (ranges.length > 12 ? ", …" : "");
    labels.push(`${label} · ${shown}` + (model.size ? ` · ${positions.length} model residues` : ""));
  }
  trace?.highlight(highlights);
  for (const [kind, { input, first }] of colourInputs) {
    const item = active.get(kind);
    const colour = (item ?? first).colour;
    if (input.value !== colour) input.value = colour;
    input.disabled = !item;
  }
  if (resetColours) {
    resetColours.disabled = !sequenceSearch?.colourChanged && !trackElements.some(({ selection }) =>
      selection && selection.colour !== selection.defaultColour);
  }
  clear.disabled = !active.size;
  detail.textContent = labels.join(" | ") || prompt;
}

function toggleTrack(item) {
  const previous = active.get(item.kind);
  previous?.control?.setAttribute("aria-pressed", "false");
  if (previous === item) active.delete(item.kind);
  else {
    active.set(item.kind, item);
    item.control.setAttribute("aria-pressed", "true");
  }
  updateSelection();
}

function pickResidue(position, reveal = false) {
  if (!Number.isInteger(position) || position < 1 || position > length) return;
  const residue = model.get(position);
  const aminoAcid = data.sequence?.[position - 1];
  const label = (aminoAcid ? aminoAcid + position : "Residue " + position)
    + (residue?.plddt == null ? "" : " · pLDDT " + residue.plddt.toFixed(1));
  active.set("residue", { ranges: [{ start: position, end: position }], label });
  updateSelection();
  if (reveal && (position < displayStart || position > displayEnd)) {
    const span = displayEnd - displayStart;
    const start = Math.max(1, Math.min(length - span, position - Math.floor(span / 2)));
    updateWindow(start, start + span);
  }
}

const layout = element("div", container, model.size ? "feature-layout linked" : "feature-layout");
const tracks = element("section", layout, "feature-tracks");
const ruler = element("div", tracks, "feature-ruler");
addTrack("navigation", ruler, 52);
if (data.sequence) addTrack("sequence", tracks, 31).sequence = data.sequence;
if (model.size) {
  if (hasConfidence) {
    const row = element("div", tracks, "protein-feature-row");
    element("div", row, "protein-feature-label", "Model confidence · pLDDT");
    const graph = addTrack("linegraph-track", row, 84);
    const axis = element("div", row, "confidence-axis");
    for (const value of [100, 50, 0]) element("span", axis, "", String(value));
    graph.setAttribute("highlight-on-click", "");
    graph.data = [{
      name: "pLDDT", range: [0, 100], color: "#206a87",
      values: Array.from({ length }, (_, index) => ({
        position: index + 1, value: model.get(index + 1)?.plddt ?? null,
      })),
    }];
    const mean = confidenceValues.reduce((total, value) => total + value, 0)
      / confidenceValues.length;
    const source = data.confidence_source ? " · " + data.confidence_source : "";
    const score = "Mean pLDDT " + mean.toFixed(1)
      + " · " + confidenceValues.length + "/" + length + " residues" + source;
    element("p", row, "confidence-summary", score);
    const help = element("details", row, "confidence-help");
    element("summary", help, "", "❓ pLDDT help");
    element("p", help, "", "pLDDT is local prediction confidence on a 0–100 scale. "
      + "Select a residue to read its score. The mean uses residues with a confidence value. "
      + "WhatRes realism and apparent resolution describe the geometry of the whole model.");
  } else {
    element("p", tracks, "", "Per-residue pLDDT is unavailable in this review.");
  }
}

/** Apply one feature's colour to both its Nightingale marks and its selection control. */
function setTrackColour(item, colour) {
  item.colour = colour;
  item.control.style.setProperty("--selection-colour", colour);
  item.track.setAttribute("highlight-color", colour);
  item.track.data = [model.size ? { ...item.feature, color: colour } : item.feature];
}

function featureRow(parent, feature, label, kind) {
  const row = element("div", parent, "protein-feature-row");
  const header = element("div", row, "protein-feature-label");
  const ranges = feature.locations.flatMap(location => location.fragments);
  const defaultColour = kind === "pocket" && /^#[\da-f]{6}$/i.test(feature.color)
    ? feature.color.toLowerCase() : HIGHLIGHT_COLOURS[kind];
  const item = { ranges, label, kind, feature, defaultColour };
  item.control = button(header, label, () => toggleTrack(item), "feature-track-label");
  item.control.setAttribute("aria-pressed", "false");
  const text = feature.rangeText || ranges.map(({ start, end }) =>
    start === end ? String(start) : start + "–" + end).join(", ");
  element("span", header, "", text);
  item.track = addTrack("track", row, 20);
  item.track.selection = item;
  setTrackColour(item, defaultColour);
}

const domains = new Map();
for (const feature of data.features || []) {
  const key = JSON.stringify([feature.accession, feature.description, feature.color, feature.provenance]);
  if (!domains.has(key)) domains.set(key, { ...feature, intervals: new Map() });
  const domain = domains.get(key);
  for (const location of feature.locations) {
    for (const fragment of location.fragments) domain.intervals.set(`${fragment.start}:${fragment.end}`, fragment);
  }
}
const shown = Math.min(domains.size, 100);
if (shown) {
  if (model.size) element("h3", tracks, "", "Protein domains");
  if (shown < domains.size) {
    element("p", tracks, "", "Showing " + shown + " of " + domains.size + " feature tracks.");
  }
  const displayed = [...domains.values()].slice(0, shown);
  if (model.size && displayed.some(item => item.provenance === "recorded_coordinates")) {
    element("p", tracks, "domain-provenance", "Recorded domains match accession and length. "
      + "Their annotation sequence has no checksum, so the model overlay is approximate.");
  }
  for (const { intervals, ...feature } of displayed) {
    const label = [feature.accession, feature.description].filter(Boolean).join(" · ");
    const fragments = [...intervals.values()].sort((a, b) => a.start - b.start || a.end - b.end);
    const positions = fragments.map(({ start, end }) => start === end ? `${start}` : `${start}–${end}`).join(", ");
    const provenance = { recorded_coordinates: "Recorded coordinates", sequence_verified: "Sequence verified" };
    const suffix = model.size && provenance[feature.provenance] ? ` · ${provenance[feature.provenance]}` : "";
    featureRow(tracks, { ...feature, locations: [{ fragments }], rangeText: positions + suffix },
      label || "Protein feature", "domain");
  }
} else if (!model.size) {
  element("p", tracks, "", "No positional features are available for this sequence.");
}

if (pockets.length) {
  element("h3", tracks, "", "Mapped pocket residues");
  for (const pocket of pockets) {
    const label = "Pocket " + pocket.number + " · rank " + pocket.rank;
    featureRow(tracks, {
      accession: "pocket-" + pocket.rank + "-" + pocket.number, color: pocket.color,
      rangeText: pocket.positions.length + " mapped residues",
      locations: pocket.positions.map(position => ({ fragments: [{ start: position, end: position }] })),
    }, label, "pocket");
  }
}

if (model.size) {
  const structure = element("section", layout, "linked-structure");
  element("h3", structure, "", "Model · Cα trace");
  trace = mountStructureTrace(structure, [...model.values()], position => pickResidue(position, true));
  const controls = element("div", structure, "structure-controls");
  button(controls, "Fit model", trace.fit);
  button(controls, "Zoom in", () => trace.magnify(1.2));
  button(controls, "Zoom out", () => trace.magnify(1 / 1.2));
  let colourByConfidence = null;
  if (hasConfidence) {
    const label = element("label", controls, "confidence-colouring");
    colourByConfidence = element("input", label);
    colourByConfidence.type = "checkbox";
    colourByConfidence.checked = true;
    label.append(" Colour trace by pLDDT");
  }
  const residueLabel = element("label", controls, "", "Residue ");
  const residueInput = element("input", residueLabel, "feature-residue-input");
  residueInput.type = "number";
  residueInput.min = 1;
  residueInput.max = length;
  residueInput.addEventListener("change", () => pickResidue(Number(residueInput.value), true));
  element("p", structure, "", "Drag to rotate. Click a point to select its sequence position.");
  if (data.sequence) {
    const row = element("div", tracks, "protein-feature-row");
    row.hidden = true;
    element("div", row, "protein-feature-label", "Amino-acid sequence matches");
    const matchTrack = addTrack("track", row, 16);
    sequenceSearch = mountSequenceSearch(structure, ({
      ranges, colour, summary, query, regularExpression,
    }) => {
      row.hidden = !ranges.length;
      sequenceSearchLabel = `${regularExpression ? "Regex " : ""}${query} · ${summary}`;
      matchTrack.data = ranges.length ? [{
        accession: "sequence-matches", color: colour, locations: [{ fragments: ranges }],
      }] : [];
      if (ranges.length) active.set("sequence", { ranges, colour });
      else active.delete("sequence");
      updateSelection();
    });
    sequenceSearch.setSequence(data.sequence);
  }
  if (sequenceSearch || trackElements.some(track => track.selection)) {
    const colours = element("div", structure, "trace-colour-controls");
    for (const [kind, label] of [["domain", "Domain colour"], ["pocket", "Pocket colour"]]) {
      const first = trackElements.find(track => track.selection?.kind === kind)?.selection;
      if (!first) continue;
      const field = element("label", colours, "trace-colour-picker", label);
      field.title = `Select a ${kind} track to change its colour`;
      const input = element("input", field);
      input.type = "color";
      const change = () => {
        const item = active.get(kind);
        if (!item || item.colour === input.value) return;
        setTrackColour(item, input.value);
        updateSelection();
      };
      input.addEventListener("input", change);
      input.addEventListener("change", change);
      colourInputs.set(kind, { input, first });
    }
    resetColours = button(colours, "Reset colours", () => {
      for (const { selection } of trackElements) {
        if (selection && selection.colour !== selection.defaultColour) {
          setTrackColour(selection, selection.defaultColour);
        }
      }
      sequenceSearch?.resetColour();
      updateSelection();
    });
  }
  const legend = element("div", structure, "trace-legend");
  const picked = element("span", legend, "", "Selected residue");
  picked.style.setProperty("--trace-colour", HIGHLIGHT_COLOURS.residue);
  const confidenceColours = [
    ...CONFIDENCE_BANDS, { colour: NEUTRAL_TRACE_COLOUR, label: "Unavailable" },
  ];
  const bands = confidenceColours.map(({ colour, label }) => {
    const item = element("span", legend, "", label);
    item.style.setProperty("--trace-colour", colour);
    item.hidden = !hasConfidence;
    return item;
  });
  const neutralLabel = hasConfidence ? "Uncoloured trace" : "pLDDT unavailable";
  const neutral = element("span", legend, "", neutralLabel);
  neutral.style.setProperty("--trace-colour", NEUTRAL_TRACE_COLOUR);
  neutral.hidden = hasConfidence;
  colourByConfidence?.addEventListener("change", () => {
    const enabled = colourByConfidence.checked;
    trace.setConfidenceColouring({ enabled });
    for (const item of bands) item.hidden = !enabled;
    neutral.hidden = enabled;
  });
  const exportRow = element("div", structure, "structure-controls");
  const exportStatus = element("span", exportRow, "", "");
  exportStatus.setAttribute("role", "status");
  button(exportRow, "Download 3D view (PDF)", () => {
    const { canvasPdf, downloadBlob, safePdfName } = globalThis.E3ViewerPdf;
    const highlights = [...active].map(([kind, item]) => ({
      label: kind === "sequence" ? `Matches: ${sequenceSearchLabel}` : item.label,
      colour: item.colour ?? HIGHLIGHT_COLOURS[kind],
    }));
    const key = highlights.concat(colourByConfidence?.checked
      ? confidenceColours.map(({ colour, label }) => ({ colour, label: `pLDDT ${label}` }))
      : [{ colour: NEUTRAL_TRACE_COLOUR, label: neutralLabel }]);
    const title = data.model_label || "Protein structure";
    try {
      const canvas = structure.querySelector(".linked-trace");
      downloadBlob(canvasPdf({
        canvas: trace.snapshot(), title, subtitle: `Cα trace · ${scope}`, legend: key,
        background: getComputedStyle(canvas).backgroundColor,
      }), `${safePdfName(data.file_stem || title)}_3d_view.pdf`);
      exportStatus.textContent = "";
    } catch (error) {
      exportStatus.textContent = error.message;
    }
  });
  exportRow.appendChild(exportStatus);
  updateSelection();
}

container.addEventListener("change", event => {
  const data = event.detail;
  if (!data) return;
  if (data["display-start"] !== undefined && data["display-end"] !== undefined) {
    updateWindow(data["display-start"], data["display-end"]);
  }
  if ((data.eventType || data.eventtype) !== "click") return;
  const track = event.target;
  if (track.selection) {
    toggleTrack(track.selection);
  } else if (track.localName === "nightingale-linegraph-track" && data.highlight) {
    pickResidue(Number(data.highlight.split(":")[0]));
  } else if (data.feature?.position) {
    pickResidue(Number(data.feature.position));
  }
});
