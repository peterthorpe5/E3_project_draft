# Changelog

## 0.1.3 - 2026-09-01

- Fix the JavaScript function-name collision that stopped every run-wide chart
  after the static HTML headings appeared.
- Add a visible in-page rendering error so browser failures cannot remain silent.
- Reduce standalone report size by retaining only browser-used fields and by
  embedding fixed-width distance histogram bins instead of every pair value.
- Lower the default embedded group-summary bound to 20,000 and enforce a
  browser-safety ceiling of 50,000 rows; deterministic stratified sampling retains
  representation across group types and hierarchy levels.
- Ensure distance-backed networks use the exact distance-sampled member identifiers
  (or a deterministic subset when the report member bound is smaller).
- Add `--action report` to regenerate a separate HTML from a completed resource
  without repeating source parsing, distance calculations, Parquet or DuckDB work.
- Use scheduler-supplied node-local work storage for report input scans and remove
  temporary copies after success or failure.
- Add start, finish, elapsed-time and row/size logging for major stages, membership
  sources, every distance group, Parquet conversion and verified publication.
- Publish machine-readable `logs/stage_metrics.tsv` with every completed resource.

## 0.1.2 - 2026-08-31

- Declare every TSV column type during Parquet streaming so a late text value,
  such as HOG node `N0` after blank legacy rows, cannot conflict with null inference.
- Resolve exact, species-prefixed and OrthoFinder-internal tree leaves to canonical
  membership identifiers with explicit ambiguity and collision checks.
- Record the tree member-identifier resolution method in distance summaries.
- Add a queryable per-group/per-species copy-number relation for taxonomic and
  cluster-splitting analyses.
- Stream analytical TSV authorities directly to gzip and read compressed TSVs
  transparently during Parquet, DuckDB and HTML publication.
- Remove failed staging and incomplete copy directories by default, with an
  explicit `--keep-failed-work` diagnostic opt-in.
- Add self-contained cluster-size, species-breadth, copy-number, size/breadth,
  distance-coverage and group/species heatmap visualisations to the offline HTML.
- Bump the physical resource contract to schema version 2.

## 0.1.1 - 2026-08-31

- Stage Slurm analyses in job-specific node-local temporary storage by default.
- Add checksum-verified cross-filesystem copying followed by atomic persistent
  publication.
- Retain explicit ``--work-dir`` overrides for other schedulers and local runs.
- Default the bundled Dundee Slurm launcher to the `barton` partition.
- Add pycodestyle and pydocstyle to the reproducible Conda environment used by
  the complete release gate.

## 0.1.0 - 2026-08-31

- Add version-aware OrthoFinder 2 and 3 result discovery.
- Add long-form species, sequence, orthogroup and all-level HOG publication.
- Add tree inventories and optional Newick node/edge publication.
- Add explicit pairwise alignment and patristic-distance calculations.
- Add automatic alignment-to-resolved-tree distance fallback with per-cluster
  source provenance and explicit unavailable reasons.
- Add versioned Parquet, DuckDB, TSV, QC and provenance resources.
- Add an offline interactive HTML report with a Cytoscape-style network view.
