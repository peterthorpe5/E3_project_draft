/** Display validated one-based inclusive protein features using Nightingale. */
import Sequence from "@nightingale-elements/nightingale-sequence";
import Navigation from "@nightingale-elements/nightingale-navigation";
import Track from "@nightingale-elements/nightingale-track";
for (const [name, component] of [["nightingale-sequence", Sequence], ["nightingale-navigation", Navigation], ["nightingale-track", Track]]) {
  if (!customElements.get(name)) customElements.define(name, component);
}
const data = JSON.parse(document.getElementById("protein-data").textContent);
const container = document.getElementById("viewer");
for (const name of ["navigation", "sequence", "track"]) {
  const element = document.createElement("nightingale-" + name);
  element.setAttribute("length", String(data.sequence.length));
  element.setAttribute("displaystart", "1");
  element.setAttribute("displayend", String(data.sequence.length));
  element.setAttribute("height", name === "track" ? "120" : "60");
  element.setAttribute("highlight-event", "onmouseover");
  container.appendChild(element);
  if (name === "sequence") element.sequence = data.sequence;
  if (name === "track") element.data = data.features;
}
container.addEventListener("change", (event) => {
  const detail = event.detail || {};
  if (detail.displaystart !== undefined && detail.displayend !== undefined) {
    for (const element of container.children) {
      element.setAttribute("displaystart", String(detail.displaystart));
      element.setAttribute("displayend", String(detail.displayend));
    }
  }
});
container.addEventListener("mouseover", (event) => {
  const feature = event.detail?.feature;
  if (feature) document.getElementById("status").textContent = feature.accession || "Protein feature";
});
document.getElementById("status").textContent = "Nightingale · sequence and predicted domain coordinates";
