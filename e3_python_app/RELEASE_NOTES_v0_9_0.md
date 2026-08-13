# ARIA E3 Python reporter v0.9.0

- Adds a separate **DeepClust and 1KP sequence neighbourhoods** panel below the
  OrthoFinder view. It reports cluster-level raw/strict 1KP sample and parsed
  species coverage from `candidate_evidence`, supports one or several inherited
  seed filters and preserves optional links to reconciled evolutionary groups.
- Keeps the scientific boundary explicit: DeepClust membership is sequence-space
  discovery evidence and is never labelled as inferred orthology or proof that
  every member is an E3 ligase.
- Adds independent linear/logarithmic x- and y-axis controls to the OrthoFinder
  group-size and 1KP-coverage plots. PDF exports preserve the active scales.
- Upgrades compatible legacy pocket-review HTML in memory with functional
  **Download current view PDF** and **Download alignment PDF** controls. The
  source review bundle remains read-only.
- Packages and validates the offline browser PDF compatibility asset.
