/** Amino-acid search shared by the offline structure viewers. */
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

/** Find overlapping regex matches on the ungapped sequence, skipping empty spans. */
export function regexMatches({ sequence, query }) {
  const expression = new RegExp(query, "gi");
  const ranges = [];
  for (let match = expression.exec(sequence); match; match = expression.exec(sequence)) {
    if (match[0].length) {
      ranges.push({ start: match.index + 1, end: match.index + match[0].length });
    }
    expression.lastIndex = match.index + 1;
  }
  return ranges;
}

/** Run the browser's regex engine off the UI thread and return a cancellation function. */
function runRegexSearch({ sequence, query, onResult }) {
  // Only the matching function is embedded in the worker. The pattern arrives as data.
  const source = `self.onmessage = ({ data }) => {
    try {
      self.postMessage({ matches: (${regexMatches.toString()})(data) });
    } catch (error) {
      self.postMessage({ error: error.message });
    }
  };`;
  const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
  let worker;
  try {
    worker = new Worker(url);
  } catch (error) {
    URL.revokeObjectURL(url);
    throw new Error("Regular expression search is unavailable in this viewer.", { cause: error });
  }
  const timer = setTimeout(() => finish({
    error: "This regular expression took too long. Try a simpler pattern.",
  }), 2000);

  function stop() {
    clearTimeout(timer);
    worker.onmessage = worker.onerror = null;
    worker.terminate();
    URL.revokeObjectURL(url);
  }

  function finish(result) {
    stop();
    onResult(result);
  }

  worker.onmessage = ({ data }) => finish(data);
  worker.onerror = event => {
    event.preventDefault();
    finish({ error: "The viewer could not run this regular expression." });
  };
  worker.postMessage({ sequence, query });
  return stop;
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
      <label class="sequence-search-query">Amino-acid sequence
        <input type="text" placeholder="e.g. QWFAA" spellcheck="false" autocomplete="off">
      </label>
      <label class="sequence-search-regex" title="Use a pattern such as QW.A[AV]">
        <input type="checkbox"> Regular expression
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
  const query = form.querySelector('input[type="text"]');
  const regex = form.querySelector('input[type="checkbox"]');
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
  let cancelRegex = null;

  function update() {
    const single = mode.value === "one";
    const index = Math.min(Math.max(1, Math.trunc(Number(occurrence.value)) || 1), matches.length);
    if (index) occurrence.value = String(index);
    occurrence.max = String(matches.length);
    occurrence.parentElement.hidden = !single || !matches.length;
    mode.disabled = matches.length < 2;
    query.disabled = find.disabled = regex.disabled = !sequence;
    clear.disabled = !searched && !query.value;
    const ranges = single ? matches.slice(index - 1, index) : matches;
    const shown = ranges.slice(0, 8).map(({ start, end }) =>
      start === end ? String(start) : `${start}–${end}`).join(", ");
    const coordinates = shown + (ranges.length > 8 ? ", …" : "");
    const summary = single && matches.length > 1
      ? `Match ${index} of ${matches.length}` : `${matches.length} ${matches.length === 1 ? "match" : "matches"}`;
    status.textContent = !sequence ? "A verified sequence is unavailable for this structure."
      : cancelRegex ? "Searching…"
      : error || (matches.length ? `${summary} · ${coordinates}`
        : searched ? (regex.checked ? "No matching residues." : "No exact matches.") : "");
    onSelection({ ranges: combineRanges(ranges), colour: colour.value, summary: status.textContent,
      query: appliedQuery, regularExpression: regex.checked });
  }

  function showResult({ matches: found = [], error: problem = "" }) {
    cancelRegex = null;
    matches = found;
    error = problem;
    if (matches.length < 2) mode.value = "all";
    update();
  }

  function search() {
    cancelRegex?.();
    cancelRegex = null;
    const value = query.value;
    appliedQuery = regex.checked ? value : value.replace(/\s/g, "").toUpperCase();
    searched = Boolean(appliedQuery);
    query.placeholder = regex.checked ? "e.g. QW.A[AV]" : "e.g. QWFAA";
    if (regex.checked) query.removeAttribute("maxlength");
    else query.maxLength = sequence.length + 100;
    occurrence.value = "1";
    if (!sequence || !searched) {
      showResult({});
      return;
    }
    try {
      if (regex.checked) {
        cancelRegex = runRegexSearch({ sequence, query: value, onResult: showResult });
        matches = [];
        error = "";
        update();
      } else {
        showResult({ matches: sequenceMatches({ sequence, query: value }) });
      }
    } catch (exc) {
      showResult({ error: exc.message });
    }
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    search();
  });
  query.addEventListener("input", () => { clear.disabled = !searched && !query.value; });
  regex.addEventListener("change", search);
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
