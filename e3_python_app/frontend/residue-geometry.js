/** Scales and linked sequence marks for WhatRes local geometry. */
export const MISSING = "#8d9aa7";
const SURPRISE = ["#f9eac5", "#efbe69", "#d87a48", "#a34352", "#551643"];
export const FLAG_BANDS = [
  { colour: "#84aaa7", label: "0 outliers" }, { colour: "#e4ac49", label: "1 outlier" },
  { colour: "#c45b47", label: "2 outliers" }, { colour: "#641746", label: "3+ outliers" },
];

/** Map numerical surprise to a full-model scale, retaining true zeros and missingness. */
export function surpriseColour({ value, limit }) {
  if (!Number.isFinite(value) || value < 0 || !Number.isFinite(limit) || limit < 0) return MISSING;
  const ratio = limit === 0 ? Number(value > 0) : Math.min(1, value / limit);
  const scaled = ratio * (SURPRISE.length - 1);
  const index = Math.floor(scaled);
  if (index === scaled) return SURPRISE[index];
  const fraction = scaled - index;
  const channels = [1, 3, 5].map(offset => {
    const a = parseInt(SURPRISE[index].slice(offset, offset + 2), 16);
    const b = parseInt(SURPRISE[index + 1].slice(offset, offset + 2), 16);
    return Math.round(a + fraction * (b - a)).toString(16).padStart(2, "0");
  });
  return "#" + channels.join("");
}

/** Return a colour for the number of flagged measurements at a residue. */
export function outlierColour({ count }) {
  return Number.isInteger(count) && count >= 0 ? FLAG_BANDS[Math.min(count, 3)].colour : MISSING;
}

/** Produce the same numerical key for the on-screen trace and its PDF. */
export function geometryLegend({ mode, limit }) {
  const bands = mode === "outliers" ? FLAG_BANDS : limit === 0
    ? [{ colour: SURPRISE[0], label: "0 surprise" }, { colour: SURPRISE.at(-1), label: ">0 surprise" }]
    : [0, .5, 1].map(fraction => ({
      colour: surpriseColour({ value: fraction * limit, limit }),
      label: (fraction === 1 ? "≥" : "") + (fraction * limit).toFixed(1) + " surprise",
    }));
  return [...bands, { colour: MISSING, label: "Geometry unavailable" }];
}

/** Describe the measured geometry in words for pointers, keyboard users and exports. */
export function geometryDetail({ residue }) {
  if (!Number.isFinite(residue?.residue_score))
    return "Geometry unavailable" + (residue?.status ? " · " + residue.status.replaceAll("_", " ") : "");
  const count = residue.n_outliers;
  return "Surprise " + residue.residue_score.toFixed(2)
    + " · " + count + (count === 1 ? " outlier" : " outliers")
    + (residue.worst_metric ? " · worst " + residue.worst_metric : "");
}

/** Preserve narrow peaks and outlier flags when several residues share a drawing column. */
export function geometryBins({ model, start, end, maxColumns }) {
  const span = end - start + 1;
  const count = Math.min(span, maxColumns);
  const bins = Array.from({ length: count }, () => ({ peak: null, flagged: false }));
  for (let pos = start; pos <= end; pos++) {
    const residue = model.get(pos);
    if (!Number.isFinite(residue?.residue_score)) continue;
    const bin = bins[Math.floor((pos - start) * count / span)];
    bin.peak = bin.peak === null ? residue.residue_score : Math.max(bin.peak, residue.residue_score);
    bin.flagged ||= residue.n_outliers > 0;
  }
  return bins;
}

/** Mount the keyboard-accessible geometry strip on the same window as the sequence tracks. */
export function mountGeometryStrip({ container, model, length, limit, onPick }) {
  const canvas = document.createElement("canvas");
  canvas.className = "geometry-strip";
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "slider");
  canvas.setAttribute("aria-label", "Inspect residue geometry");
  canvas.setAttribute("aria-valuemin", "1");
  canvas.setAttribute("aria-valuemax", String(length));
  container.appendChild(canvas);
  const readout = document.createElement("p");
  readout.className = "geometry-readout";
  container.appendChild(readout);
  let start = 1, end = length, position = 1, selected = null;

  function describe(pos) {
    const residue = model.get(pos);
    return (residue?.residue ?? "Residue ") + pos + " · " + geometryDetail({ residue });
  }

  function draw() {
    const width = canvas.clientWidth;
    if (!width) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(28 * ratio);
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    const bins = geometryBins({ model, start, end, maxColumns: Math.max(1, Math.floor(width)) });
    const size = width / bins.length;
    for (const [index, bin] of bins.entries()) {
      context.fillStyle = surpriseColour({ value: bin.peak, limit });
      context.fillRect(index * size, 2, size + .25, 16);
      if (bin.flagged) {
        context.fillStyle = "#25364b";
        context.fillRect(index * size, 21, Math.max(1, size), 4);
      }
    }
    if (selected !== null && selected >= start && selected <= end) {
      const x = (selected - start + .5) * width / (end - start + 1);
      context.fillStyle = "#18243b";
      context.fillRect(Math.max(0, x - 1.5), 0, 3, 20);
      context.fillStyle = "#fff";
      context.fillRect(Math.max(0, x - .5), 0, 1, 20);
    }
  }

  function underPointer(event) {
    const rect = canvas.getBoundingClientRect();
    return start + Math.max(0, Math.min(end - start,
      Math.floor((event.clientX - rect.left) * (end - start + 1) / rect.width)));
  }

  function select(pos) {
    selected = pos;
    position = pos ?? start;
    readout.textContent = pos === null ? "Point to a residue or use the arrow keys." : describe(pos);
    canvas.setAttribute("aria-valuenow", String(position));
    canvas.setAttribute("aria-valuetext", describe(position));
    draw();
  }

  canvas.addEventListener("pointermove", event => { readout.textContent = describe(underPointer(event)); });
  canvas.addEventListener("pointerleave", () => { select(selected); });
  canvas.addEventListener("click", event => onPick(underPointer(event)));
  canvas.addEventListener("keydown", event => {
    const moves = { ArrowLeft: position - 1, ArrowRight: position + 1, Home: start, End: end };
    if (!Object.hasOwn(moves, event.key)) return;
    event.preventDefault();
    onPick(Math.max(start, Math.min(end, moves[event.key])));
  });
  new ResizeObserver(draw).observe(canvas);
  select(null);
  return { select, setWindow(first, last) { start = first; end = last; select(selected); } };
}
