/** Literal amino-acid search shared by the offline structure viewers. */
export const SEQUENCE_COLOUR = "#e32860";

/** Return every inclusive one-based match, including overlapping occurrences. */
export function sequenceMatches({ sequence, query }) {
  const letters = query.replace(/\s/g, "");
  if (!letters) return [];
  if (!/^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$/i.test(letters)) {
    throw new Error("Use amino-acid letters, for example QWFAA.");
  }
  const pattern = letters.toUpperCase();
  const ranges = [];
  for (let start = sequence.indexOf(pattern); start !== -1;
    start = sequence.indexOf(pattern, start + 1)) {
    ranges.push({ start: start + 1, end: start + pattern.length });
  }
  return ranges;
}

/** Collapse sorted matches to disjoint residue ranges for rendering. */
export function combineRanges(ranges) {
  const combined = [];
  for (const { start, end } of ranges) {
    const last = combined.at(-1);
    if (last && start <= last.end + 1) last.end = Math.max(last.end, end);
    else combined.push({ start, end });
  }
  return combined;
}

/** Build a set of the exact residue positions in the displayed intervals. */
export function rangePositions(ranges) {
  const positions = new Set();
  for (const { start, end } of ranges) {
    for (let position = start; position <= end; position += 1) positions.add(position);
  }
  return positions;
}

/** Mount local search, occurrence selection and colour controls for a protein. */
export function mountSequenceSearch(parent, onSelection) {
  const panel = document.createElement("section");
  panel.className = "sequence-search";
  panel.innerHTML = `
    <form>
      <label>Amino-acid sequence
        <input type="text" placeholder="e.g. QWFAA" spellcheck="false" autocomplete="off">
      </label>
      <button type="submit">Find matches</button>
      <button type="button">Clear matches</button>
    </form>
    <div class="sequence-search-options">
      <label>Highlight
        <select aria-label="Highlight"><option value="all">All matches</option><option value="one">One match</option></select>
      </label>
      <label class="sequence-occurrence" hidden>Match number
        <input type="number" min="1" step="1" value="1">
      </label>
      <label class="trace-colour-picker">Match colour
        <input type="color" value="${SEQUENCE_COLOUR}">
      </label>
    </div>
    <p role="status" aria-live="polite"></p>`;
  parent.appendChild(panel);
  const form = panel.querySelector("form");
  const query = form.querySelector("input");
  const find = form.querySelector('button[type="submit"]');
  const clear = form.querySelector('button[type="button"]');
  const mode = panel.querySelector("select");
  const occurrence = panel.querySelector('input[type="number"]');
  const colour = panel.querySelector('input[type="color"]');
  const status = panel.querySelector("p");
  let sequence = "";
  let matches = [];
  let searched = false;
  let error = "";
  let appliedQuery = "";

  function update() {
    const single = mode.value === "one";
    const index = Math.min(Math.max(1, Math.trunc(Number(occurrence.value)) || 1), matches.length);
    if (index) occurrence.value = String(index);
    occurrence.max = String(matches.length);
    occurrence.parentElement.hidden = !single || !matches.length;
    mode.disabled = matches.length < 2;
    query.disabled = find.disabled = !sequence;
    clear.disabled = !searched && !query.value;
    const ranges = single ? matches.slice(index - 1, index) : matches;
    const shown = ranges.slice(0, 8).map(({ start, end }) =>
      start === end ? String(start) : `${start}–${end}`).join(", ");
    const coordinates = shown + (ranges.length > 8 ? ", …" : "");
    const summary = single && matches.length > 1
      ? `Match ${index} of ${matches.length}` : `${matches.length} ${matches.length === 1 ? "match" : "matches"}`;
    status.textContent = !sequence ? "A verified sequence is unavailable for this structure."
      : error || (matches.length ? `${summary} · ${coordinates}`
        : searched ? "No exact matches." : "");
    onSelection({ ranges: combineRanges(ranges), colour: colour.value, summary: status.textContent,
      query: appliedQuery });
  }

  function search() {
    searched = Boolean(query.value.trim());
    matches = [];
    error = "";
    appliedQuery = query.value.replace(/\s/g, "").toUpperCase();
    occurrence.value = "1";
    try {
      matches = sequenceMatches({ sequence, query: query.value });
    } catch (exc) {
      error = exc.message;
    }
    if (matches.length < 2) mode.value = "all";
    update();
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    search();
  });
  query.addEventListener("input", () => { clear.disabled = !searched && !query.value; });
  for (const control of [mode, occurrence, colour]) control.addEventListener("change", update);
  colour.addEventListener("input", update);

  function clearMatches() {
    query.value = "";
    mode.value = "all";
    search();
  }
  clear.addEventListener("click", clearMatches);

  return {
    setSequence(value) {
      sequence = value || "";
      query.maxLength = Math.max(1, sequence.length + 100);
      search();
    },
    clear: clearMatches,
    resetColour() {
      colour.value = SEQUENCE_COLOUR;
      update();
    },
    get colourChanged() { return colour.value !== SEQUENCE_COLOUR; },
  };
}
