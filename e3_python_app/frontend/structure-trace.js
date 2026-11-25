/** An offline, residue-indexed C-alpha trace for the Nightingale view. */
import { outlierColour, surpriseColour } from "./residue-geometry.js";

export const HIGHLIGHT_COLOURS = { domain: "#182554", pocket: "#c24e00", residue: "#167d74" };
export const NEUTRAL_TRACE_COLOUR = "#8d9aa7";
export const CONFIDENCE_BANDS = [
  { minimum: 90, colour: "#1856a1", label: "90–100" },
  { minimum: 70, colour: "#188499", label: "70–<90" },
  { minimum: 50, colour: "#bc872b", label: "50–<70" },
  { minimum: 0, colour: "#a95729", label: "<50" },
];

/** Return the trace colour for a residue's pLDDT and the current display setting. */
export function confidenceColour({ value, enabled }) {
  if (!enabled || !Number.isFinite(value) || value < 0 || value > 100) return NEUTRAL_TRACE_COLOUR;
  return CONFIDENCE_BANDS.find(band => value >= band.minimum).colour;
}

/** Resolve the active trace scale for both bonds and residue markers. */
export function traceResidueColour({ residue, mode, limit }) {
  if (mode === "surprise") return surpriseColour({ value: residue.residue_score, limit });
  if (mode === "outliers") return outlierColour({ count: residue.n_outliers });
  return confidenceColour({ value: residue.plddt, enabled: mode === "plddt" });
}

export function mountStructureTrace(container, residues, onPick, limit) {
  const canvas = document.createElement("canvas");
  canvas.className = "linked-trace";
  canvas.setAttribute("aria-label", "Rotatable C-alpha trace of the selected model");
  canvas.tabIndex = 0;
  container.appendChild(canvas);
  let azimuth = .55;
  let elevation = -.28;
  let zoom = 1;
  let projected = [];
  let domains = new Set();
  let pockets = new Set();
  let matches = new Set();
  let selectedResidues = new Set();
  let domainColour = HIGHLIGHT_COLOURS.domain;
  let pocketColour = HIGHLIGHT_COLOURS.pocket;
  let matchColour;
  let colourMode = "plddt";
  let drag = null;
  let moved = false;

  const centre = [0, 0, 0];
  for (const residue of residues) {
    centre[0] += residue.x / residues.length;
    centre[1] += residue.y / residues.length;
    centre[2] += residue.z / residues.length;
  }
  const points = residues.map(residue => ({
    x: residue.x - centre[0], y: residue.y - centre[1], z: residue.z - centre[2], residue,
  }));
  const radius = points.reduce((maximum, p) => Math.max(maximum, Math.hypot(p.x, p.y, p.z)), 1);

  function paint({ surface, width, height, ratio }) {
    if (!width || !height) return [];
    surface.width = Math.round(width * ratio);
    surface.height = Math.round(height * ratio);
    const context = surface.getContext("2d");
    context.scale(ratio, ratio);
    const scale = Math.min(width, height) * .44 / radius * zoom;
    const cy = Math.cos(azimuth), sy = Math.sin(azimuth);
    const cx = Math.cos(elevation), sx = Math.sin(elevation);
    const projection = points.map(point => {
      const depth = point.z * cy - point.x * sy;
      return {
        x: width / 2 + (point.x * cy + point.z * sy) * scale,
        y: height / 2 - (point.y * cx - depth * sx) * scale,
        z: point.y * sx + depth * cx,
        residue: point.residue,
      };
    });

    const hasHighlights = Boolean(domains.size || pockets.size || matches.size
      || selectedResidues.size);
    context.lineCap = "round";
    const geometryMode = colourMode === "surprise" || colourMode === "outliers";
    const domainSegments = new Path2D();
    for (let index = 1; index < projection.length; index += 1) {
      const previous = projection[index - 1], next = projection[index];
      if (next.residue.break_before || next.residue.position !== previous.residue.position + 1) continue;
      if (!geometryMode && domains.has(previous.residue.position) && domains.has(next.residue.position)) {
        domainSegments.moveTo(previous.x, previous.y);
        domainSegments.lineTo(next.x, next.y);
        continue;
      }
      context.beginPath();
      context.strokeStyle = traceResidueColour({ residue: next.residue, mode: colourMode, limit });
      context.lineWidth = 1.65;
      context.globalAlpha = hasHighlights ? .42 : .78;
      context.moveTo(previous.x, previous.y);
      context.lineTo(next.x, next.y);
      context.stroke();
    }
    const depthOrder = [...projection].sort((a, b) => a.z - b.z);
    context.globalAlpha = hasHighlights ? .36 : 1;
    for (const point of depthOrder) {
      const position = point.residue.position;
      if (domains.has(position) || pockets.has(position) || (!geometryMode && matches.has(position))) continue;
      context.beginPath();
      context.fillStyle = traceResidueColour({ residue: point.residue, mode: colourMode, limit });
      context.arc(point.x, point.y, 2, 0, 2 * Math.PI);
      context.fill();
    }
    context.globalAlpha = 1;
    if (domains.size) {
      context.strokeStyle = "#243246";
      context.lineWidth = 6.5;
      context.stroke(domainSegments);
      context.strokeStyle = "#fff";
      context.lineWidth = 5;
      context.stroke(domainSegments);
      context.strokeStyle = domainColour;
      context.lineWidth = 3.8;
      context.stroke(domainSegments);
    }
    for (const point of depthOrder) {
      const position = point.residue.position;
      const inDomain = domains.has(position);
      const inPocket = pockets.has(position);
      const inMatch = matches.has(position);
      const selected = selectedResidues.has(position);
      if (inPocket || inDomain) {
        context.beginPath();
        context.arc(point.x, point.y, inPocket ? 4.5 : 2.8, 0, 2 * Math.PI);
        context.fillStyle = geometryMode ? traceResidueColour({ residue: point.residue, mode: colourMode, limit })
          : inPocket ? pocketColour : domainColour;
        context.fill();
        context.lineWidth = geometryMode ? 2 : inPocket ? 1.5 : 2.2;
        context.strokeStyle = geometryMode ? (inPocket ? pocketColour : domainColour) : "#243246";
        context.stroke();
        if (!inPocket) {
          context.lineWidth = 0.8;
          context.strokeStyle = "#fff";
          context.stroke();
        }
        if (inPocket && inDomain) {
          context.beginPath();
          context.arc(point.x, point.y, 6, 0, 2 * Math.PI);
          context.strokeStyle = "#fff";
          context.lineWidth = 2.8;
          context.stroke();
          context.strokeStyle = domainColour;
          context.lineWidth = 1.6;
          context.stroke();
        }
      }
      if (inMatch) {
        context.beginPath();
        context.arc(point.x, point.y, inPocket ? 8.3 : 4.5, 0, 2 * Math.PI);
        if (!geometryMode && !inPocket && !inDomain) {
          context.fillStyle = matchColour;
          context.fill();
        }
        context.strokeStyle = "#fff";
        context.lineWidth = 4;
        context.stroke();
        context.strokeStyle = matchColour;
        context.lineWidth = 2.5;
        context.stroke();
      }
      if (selected) {
        context.beginPath();
        context.arc(point.x, point.y, inMatch && inPocket ? 11 : 7, 0, 2 * Math.PI);
        context.lineWidth = 2;
        context.strokeStyle = HIGHLIGHT_COLOURS.residue;
        context.stroke();
      }
    }
    context.globalAlpha = 1;
    return projection;
  }

  function draw() {
    projected = paint({ surface: canvas, width: canvas.clientWidth, height: canvas.clientHeight,
      ratio: window.devicePixelRatio || 1 });
  }

  function fit() {
    azimuth = .55;
    elevation = -.28;
    zoom = 1;
    draw();
  }

  function magnify(factor) {
    zoom = Math.max(.35, Math.min(6, zoom * factor));
    draw();
  }

  canvas.addEventListener("pointerdown", event => {
    drag = [event.clientX, event.clientY];
    moved = false;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (!drag) return;
    const dx = event.clientX - drag[0], dy = event.clientY - drag[1];
    moved ||= Math.abs(dx) + Math.abs(dy) > 1;
    drag = [event.clientX, event.clientY];
    azimuth += dx * .012;
    elevation += dy * .012;
    draw();
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    canvas.addEventListener(name, () => { drag = null; });
  }
  canvas.addEventListener("click", event => {
    if (moved) return;
    let nearest = null, distance = 10;
    for (const point of projected) {
      const candidate = Math.hypot(point.x - event.offsetX, point.y - event.offsetY);
      if (candidate < distance || (candidate === distance && point.z > nearest?.z)) {
        nearest = point;
        distance = candidate;
      }
    }
    if (nearest) onPick(nearest.residue.position);
  });
  canvas.addEventListener("wheel", event => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    magnify(event.deltaY < 0 ? 1.13 : 1 / 1.13);
  }, { passive: false });
  canvas.addEventListener("keydown", event => {
    const angles = {
      ArrowLeft: [-.12, 0], ArrowRight: [.12, 0], ArrowUp: [0, -.12], ArrowDown: [0, .12],
    };
    if (Object.hasOwn(angles, event.key)) {
      const [dx, dy] = angles[event.key];
      azimuth += dx;
      elevation += dy;
      draw();
    } else if (["+", "=", "-"].includes(event.key)) {
      magnify(event.key === "-" ? 1 / 1.13 : 1.13);
    } else {
      return;
    }
    event.preventDefault();
  });

  new ResizeObserver(draw).observe(canvas);
  draw();
  return {
    fit, magnify,
    setColourMode({ mode }) {
      colourMode = mode;
      canvas.dataset.colourMode = mode;
      draw();
    },
    snapshot() {
      const surface = document.createElement("canvas");
      const width = canvas.clientWidth, height = canvas.clientHeight;
      paint({ surface, width, height, ratio: Math.min(3, 3200 / Math.max(width, height)) });
      return surface;
    },
    highlight({ domain, pocket, residue, sequence }) {
      domains = new Set(domain?.positions);
      pockets = new Set(pocket?.positions);
      matches = new Set(sequence?.positions);
      matchColour = sequence?.colour;
      selectedResidues = new Set(residue?.positions);
      domainColour = domain?.colour ?? HIGHLIGHT_COLOURS.domain;
      pocketColour = pocket?.colour ?? HIGHLIGHT_COLOURS.pocket;
      canvas.dataset.domainCount = String(domains.size);
      canvas.dataset.pocketCount = String(pockets.size);
      canvas.dataset.sequenceCount = String(matches.size);
      canvas.dataset.residueCount = String(selectedResidues.size);
      draw();
    },
  };
}
