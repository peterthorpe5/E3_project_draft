/** An offline, residue-indexed C-alpha trace for the Nightingale view. */
export const HIGHLIGHT_COLOURS = { domain: "#7b38b5", pocket: "#efac31", residue: "#167d74" };

export function mountStructureTrace(container, residues, onPick) {
  const canvas = document.createElement("canvas");
  canvas.className = "linked-trace";
  canvas.setAttribute("aria-label", "Rotatable C-alpha trace of the selected model");
  canvas.tabIndex = 0;
  container.appendChild(canvas);
  const context = canvas.getContext("2d");
  let azimuth = .55;
  let elevation = -.28;
  let zoom = 1;
  let projected = [];
  let domains = new Set();
  let pockets = new Set();
  let selectedResidues = new Set();
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

  function colour(confidence) {
    if (confidence === null) return "#8d9aa7";
    if (confidence >= 90) return "#1856a1";
    if (confidence >= 70) return "#188499";
    if (confidence >= 50) return "#bc872b";
    return "#a95729";
  }

  function draw() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    context.scale(ratio, ratio);
    const scale = Math.min(width, height) * .44 / radius * zoom;
    const cy = Math.cos(azimuth), sy = Math.sin(azimuth);
    const cx = Math.cos(elevation), sx = Math.sin(elevation);
    projected = points.map(point => {
      const depth = point.z * cy - point.x * sy;
      return {
        x: width / 2 + (point.x * cy + point.z * sy) * scale,
        y: height / 2 - (point.y * cx - depth * sx) * scale,
        z: point.y * sx + depth * cx,
        residue: point.residue,
      };
    });

    const hasHighlights = Boolean(domains.size || pockets.size || selectedResidues.size);
    context.lineCap = "round";
    for (let index = 1; index < projected.length; index += 1) {
      const previous = projected[index - 1], next = projected[index];
      if (next.residue.position !== previous.residue.position + 1) continue;
      context.beginPath();
      const domainSegment = domains.has(previous.residue.position) && domains.has(next.residue.position);
      context.strokeStyle = domainSegment ? HIGHLIGHT_COLOURS.domain : colour(next.residue.plddt);
      context.lineWidth = domainSegment ? 3.6 : 1.65;
      context.globalAlpha = domainSegment ? .95 : hasHighlights ? .52 : .78;
      context.moveTo(previous.x, previous.y);
      context.lineTo(next.x, next.y);
      context.stroke();
    }
    const depthOrder = [...projected].sort((a, b) => a.z - b.z);
    for (const point of depthOrder) {
      const position = point.residue.position;
      const inDomain = domains.has(position);
      const inPocket = pockets.has(position);
      const selected = selectedResidues.has(position);
      context.beginPath();
      context.globalAlpha = selected || inDomain || inPocket || !hasHighlights ? 1 : .45;
      context.fillStyle = inPocket ? HIGHLIGHT_COLOURS.pocket
        : inDomain ? HIGHLIGHT_COLOURS.domain : colour(point.residue.plddt);
      context.arc(point.x, point.y, inPocket ? 4.5 : inDomain ? 3 : 2, 0, 2 * Math.PI);
      context.fill();
      if (inPocket) {
        context.lineWidth = inDomain ? 2 : 1;
        context.strokeStyle = inDomain ? HIGHLIGHT_COLOURS.domain : "#624613";
        context.stroke();
      }
      if (selected) {
        context.beginPath();
        context.arc(point.x, point.y, 7, 0, 2 * Math.PI);
        context.lineWidth = 2;
        context.strokeStyle = HIGHLIGHT_COLOURS.residue;
        context.stroke();
      }
    }
    context.globalAlpha = 1;
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
    highlight({ domain = [], pocket = [], residue = [] }) {
      domains = new Set(domain);
      pockets = new Set(pocket);
      selectedResidues = new Set(residue);
      canvas.dataset.domainCount = String(domains.size);
      canvas.dataset.pocketCount = String(pockets.size);
      canvas.dataset.residueCount = String(selectedResidues.size);
      draw();
    },
  };
}
