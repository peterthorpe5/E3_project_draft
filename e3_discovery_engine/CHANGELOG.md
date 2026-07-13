# Changelog

## 0.1.0 - 2026-07-13

Initial production rewrite of the inherited Milestone 1 E3 discovery engine.

- Added non-destructive streaming FASTA preparation.
- Added metadata-preserving sequence and seed Parquet tables.
- Added explicit DIAMOND command construction and version checks.
- Added exact realignment outputs and strict post-realignment filters.
- Added E3-seeded cluster DuckDB and curated Parquet resources.
- Added FASTA exports with non-overclaiming names.
- Added benchmark aggregation, plots and provenance manifests.
- Added structured logging, defensive validation and atomic outputs.
- Added unit, integration, synthetic end-to-end and optional external tests.
- Preserved the inherited implementation under `legacy_reference/`.
