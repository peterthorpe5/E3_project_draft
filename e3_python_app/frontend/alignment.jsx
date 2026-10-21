/** Mount the pinned AV2 package using one React runtime. */
import React from "react";
import { createRoot } from "react-dom/client";
import { AlignmentViewer, FastaAlignment, SequenceSorter } from "alignment-viewer-2";
import "alignment-viewer-2/dist/standalone/alignmentviewer.css";

const data = JSON.parse(document.getElementById("protein-data").textContent);
try {
  const alignment = FastaAlignment.fromFileContents("Selected protein family", data.msa);
  createRoot(document.getElementById("viewer")).render(
    <AlignmentViewer alignment={alignment} sortBy={SequenceSorter.BLOSUM62_SCORE_QUERY} />
  );
  document.getElementById("status").textContent = "Alignment Viewer 2 · BLOSUM62 score to query";
} catch (error) {
  document.getElementById("status").textContent = "Viewer could not initialise: " + error.message;
}
