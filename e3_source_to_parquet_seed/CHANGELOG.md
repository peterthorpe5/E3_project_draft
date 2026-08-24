# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.4.1

<!-- source: RELEASE_NOTES_v0_4_1.md; sha256: 7e5d127b1526ab12c8df76edeb70b2d967d3b4d93093d816b459f4f57068e0ac -->

This assurance patch corrects two partial/empty-source behaviours:

- GO evidence sources are included and counted only when they contain actual
  GO, ubiquitin or exclusion evidence fields;
- typed empty protein and ligandability relations expose the full downstream
  schema when a catalogue is absent;
- Excel source workbooks are explicitly closed after every-sheet ingestion.
- Logging reconfiguration closes only package-owned handlers and leaves
  third-party root handlers intact.

A seven-source integration fixture now asserts exact known answers, and a
separate absent-catalogue fixture verifies typed empty relations. Validation:
96 tests passed with 91% branch-aware coverage.

## v0.4.0

<!-- source: RELEASE_NOTES_v0_4_0.md; sha256: 2d301eb80ede63eff88fce467cae04db29aed4f7ab4bfb1fc0cf07576cf87bfb -->

Date: 16 July 2026

### Main addition

Version 0.4.0 adds the first tested integration layer between the completed
full 1KP+ E3 Discovery Engine analysis and downstream biological candidate
prioritisation.

The build creates a 66-column evidence table with one row per E3-seeded
cluster. The production full run is expected to contribute 7,255 rows. The
source discovery DuckDB is attached read-only and is not modified.

### Formal outputs

- `e3_cluster_candidate_evidence.tsv`
- `e3_cluster_candidate_evidence.parquet`
- `e3_candidate_evidence.duckdb`
- `e3_cluster_candidate_evidence_validation.tsv`
- `e3_cluster_candidate_evidence_manifest.json`
- persistent Python and shell logs

### Scientific safeguards

The resource distinguishes inherited E3 seed evidence, strict matched seeds,
non-strict matched seeds and strict non-seed candidates. It preserves the
central interpretation that an E3-seeded sequence cluster contains at least
one inherited E3 candidate, but cluster membership does not establish that
every member is an E3 ligase.

The table is intentionally an evidence layer rather than a final biological
ranking. Domain/family confirmation, expression, orthology, audited structure
and pocket evidence, and experimental practicality still need to be added.

### Data-integrity safeguards

- validates the inspected 16 July 2026 production schema before building;
- reconciles all raw members, strict members, seed classes and strict non-seed
  candidates against their production source tables;
- validates every representative and seed metadata join;
- recalculates raw and strict sample/species-label breadth;
- verifies production seed counts and identifiers against direct links;
- validates TSV and Parquet row counts and column order after export;
- writes to unique temporary paths and publishes atomically only after all
  checks pass;
- records source path, size, modification time, SHA-256, software versions,
  output paths, named-group definitions and validation counts in provenance.

### Quality checks completed

- 87 complete package regression tests passed;
- 28 candidate-layer, CLI and release-contract tests passed under coverage;
- candidate evidence module: 99% branch-aware coverage, with no missed
  executable statements;
- every new top-level function has named test traceability;
- every Python function in the package and scripts has a docstring;
- the new integration files pass `pycodestyle` at 88 characters;
- all shell scripts pass `bash -n`;
- an isolated wheel was built successfully;
- an independent synthetic command-line smoke run produced two evidence rows,
  21 passed checks and all five formal output types.

### Production run still required

The release has been tested against a synthetic production-like DuckDB and
against a fixture generated from the real full-run schema. It must now be run
against the completed full 1KP+ DuckDB on the Dundee cluster. The formal
validation report and manifest from that run should be reviewed before the
evidence table is used for candidate ranking.
