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
const tracks = data.sequence ? ["navigation", "sequence", "track"] : ["navigation", "track"];
for (const name of tracks) {
  const element = document.createElement("nightingale-" + name);
  element.setAttribute("length", String(length));
  element.setAttribute("display-start", "1");
  element.setAttribute("display-end", String(length));
  element.setAttribute("height", name === "track" ? "120" : "60");
  element.setAttribute("highlight-event", "onmouseover");
  container.appendChild(element);
  if (name === "sequence") element.sequence = data.sequence;
  if (name === "track") element.data = data.features;
}
container.addEventListener("change", (event) => {
  const detail = event.detail || {};
  if (detail["display-start"] !== undefined && detail["display-end"] !== undefined) {
    for (const element of container.children) {
      element.setAttribute("display-start", String(detail["display-start"]));
      element.setAttribute("display-end", String(detail["display-end"]));
    }
  }
});
container.addEventListener("mouseover", (event) => {
  const feature = event.detail?.feature;
  if (feature) document.getElementById("status").textContent = feature.accession || "Protein feature";
});
document.getElementById("status").textContent = data.coordinate_scope ||
  "Nightingale · sequence and predicted domain coordinates";
