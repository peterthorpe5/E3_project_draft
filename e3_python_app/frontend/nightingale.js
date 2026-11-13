/** Display clickable domains and exact model evidence using Nightingale. */
import Sequence from "@nightingale-elements/nightingale-sequence";
import Navigation from "@nightingale-elements/nightingale-navigation";
import Track from "@nightingale-elements/nightingale-track";
import Linegraph from "@nightingale-elements/nightingale-linegraph-track";
import { mountStructureTrace, HIGHLIGHT_COLOURS } from "./structure-trace.js";

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
const pockets = data.pockets || [];
const trackElements = [];
const active = new Map();
let trace = null;
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
  updateSelection();
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
  for (const [kind, { ranges, label }] of active) {
    const positions = [...model.keys()].filter(position =>
      ranges.some(({ start, end }) => start <= position && position <= end));
    highlights[kind] = positions;
    const coordinates = ranges.slice(0, 12).map(({ start, end }) =>
      start === end ? String(start) : start + "–" + end).join(", ");
    const shown = coordinates + (ranges.length > 12 ? ", …" : "");
    labels.push(`${label} · ${shown}` + (model.size ? ` · ${positions.length} model residues` : ""));
  }
  trace?.highlight(highlights);
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
  const hasConfidence = [...model.values()].some(residue => residue.plddt !== null);
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
  } else {
    element("p", tracks, "", "Per-residue pLDDT is unavailable in this review.");
  }
}

function featureRow(parent, feature, label, kind) {
  const row = element("div", parent, "protein-feature-row");
  const header = element("div", row, "protein-feature-label");
  const ranges = feature.locations.flatMap(location => location.fragments);
  const item = { ranges, label, kind };
  item.control = button(header, label, () => toggleTrack(item), "feature-track-label");
  item.control.setAttribute("aria-pressed", "false");
  item.control.style.setProperty("--selection-colour", HIGHLIGHT_COLOURS[kind]);
  const text = feature.rangeText || ranges.map(({ start, end }) =>
    start === end ? String(start) : start + "–" + end).join(", ");
  element("span", header, "", text);
  const track = addTrack("track", row, 20);
  track.selection = item;
  track.setAttribute("highlight-color", HIGHLIGHT_COLOURS[kind]);
  track.data = [feature];
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
  const residueLabel = element("label", controls, "", "Residue ");
  const residueInput = element("input", residueLabel, "feature-residue-input");
  residueInput.type = "number";
  residueInput.min = 1;
  residueInput.max = length;
  residueInput.addEventListener("change", () => pickResidue(Number(residueInput.value), true));
  element("p", structure, "", "Drag to rotate. Click a point to select its sequence position.");
  const highlights = element("div", structure, "trace-legend");
  for (const [kind, label] of [["domain", "Domain"], ["pocket", "Pocket"], ["residue", "Selected residue"]]) {
    const item = element("span", highlights, "", label);
    item.style.setProperty("--trace-colour", HIGHLIGHT_COLOURS[kind]);
  }
  const legend = element("div", structure, "trace-legend");
  for (const [colour, label] of [
    ["#1856a1", "90–100"], ["#188499", "70–<90"], ["#bc872b", "50–<70"],
    ["#a95729", "<50"], ["#8d9aa7", "Unavailable"],
  ]) {
    const item = element("span", legend, "", label);
    item.style.setProperty("--trace-colour", colour);
  }
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
