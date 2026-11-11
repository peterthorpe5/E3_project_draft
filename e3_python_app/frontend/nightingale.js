/** Display validated one-based inclusive protein features using Nightingale. */
import Sequence from "@nightingale-elements/nightingale-sequence";
import Navigation from "@nightingale-elements/nightingale-navigation";
import Track from "@nightingale-elements/nightingale-track";
for (const [name, component] of [["nightingale-sequence", Sequence], ["nightingale-navigation", Navigation], ["nightingale-track", Track]]) {
  if (!customElements.get(name)) customElements.define(name, component);
}
const data = JSON.parse(document.getElementById("protein-data").textContent);
const container = document.getElementById("viewer");
const length = data.sequence ? data.sequence.length : data.length;
if (!Number.isInteger(length) || length < 1) throw new Error("Missing protein coordinate length");
function addTrack(name, parent, height) {
  const element = document.createElement("nightingale-" + name);
  element.setAttribute("length", String(length));
  element.setAttribute("display-start", "1");
  element.setAttribute("display-end", String(length));
  element.setAttribute("height", String(height));
  element.setAttribute("highlight-event", "onmouseover");
  parent.appendChild(element);
  return element;
}
container.classList.add("protein-feature-viewer");
addTrack("navigation", container, 54);
if (data.sequence) addTrack("sequence", container, 38).sequence = data.sequence;
const groups = new Map();
for (const feature of data.features || []) {
  const key = JSON.stringify([feature.accession, feature.description]);
  if (!groups.has(key)) groups.set(key, { ...feature, locations: [] });
  groups.get(key).locations.push(...feature.locations);
}
const status = document.getElementById("status");
const scope = data.coordinate_scope || "Exact sequence coordinates";
const shown = Math.min(groups.size, 100);
status.textContent = `Nightingale · ${length} residues · ${scope}`;
const summary = document.createElement("p");
summary.textContent = groups.size ? `${shown} of ${groups.size} feature tracks` :
  "No positional features are available for this sequence.";
container.appendChild(summary);
for (const feature of Array.from(groups.values()).slice(0, shown)) {
  const row = document.createElement("div");
  row.className = "protein-feature-row";
  const label = document.createElement("div");
  label.className = "protein-feature-label";
  const segments = feature.locations.flatMap(location => location.fragments)
    .map(fragment => `${fragment.start}–${fragment.end}`);
  const uniqueSegments = [...new Set(segments)];
  label.textContent = [feature.accession, feature.description].filter(Boolean).join(" · ") ||
    "Protein feature";
  const range = document.createElement("span");
  range.textContent = uniqueSegments.join(", ");
  label.appendChild(range);
  row.appendChild(label);
  container.appendChild(row);
  addTrack("track", row, 24).data = [feature];
}
container.addEventListener("change", (event) => {
  const detail = event.detail || {};
  if (detail["display-start"] !== undefined && detail["display-end"] !== undefined) {
    for (const element of container.querySelectorAll("[display-start]")) {
      element.setAttribute("display-start", String(detail["display-start"]));
      element.setAttribute("display-end", String(detail["display-end"]));
    }
  }
});
