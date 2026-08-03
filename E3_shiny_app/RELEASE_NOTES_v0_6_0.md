# ARIA plant E3 Shiny reporter v0.6.0

## Selected-group visual review

- Adds a **3D structures & pockets** tab without removing or replacing any
  existing application tab.
- Adds a separate **Pocket-aligned sequences** tab for the published MAFFT
  alignment and exact pocket-residue highlights.
- Uses the existing checksum-bound, self-contained pocket-review bundle rather
  than attempting to follow inaccessible cluster paths from a copied DuckDB.
- Provides a searchable rank, evolutionary-group, lead-cluster and reference
  accession selector.
- Defaults to the first group in the authoritative review order and never
  recalculates candidate ranking.
- Exposes the original group-member accession/name values, stable FASTA export
  identifiers, species, reference status and pocket-evidence status.
- Provides selected-group TSV downloads and direct links to the full ranked
  review index and cross-group structural evidence matrix.
- Shows unavailable models and unassessed members explicitly rather than
  interpreting them as biological negatives.

## Portable release behaviour

- Adds `--pocket_review_dir` and `E3_POCKET_REVIEW_DIR` configuration options.
- Automatically discovers the bundle only when exactly one valid direct
  `pocket_review*` directory exists beside the selected DuckDB or Parquet.
- Rejects incomplete bundles, unsafe group-page paths, duplicate ranks and
  ambiguous automatic discovery.
- Serves the report locally through a read-only Shiny resource mapping; no
  network connection, CDN or remote structure service is required.

## Interpretation boundary

The embedded 3D view is a rotatable C-alpha trace with mapped pocket residues,
not an atomistic surface, docking result or binding prediction. It visualises
completed evidence without rerunning pocket detection, MAFFT, US-align or
TM-align.
