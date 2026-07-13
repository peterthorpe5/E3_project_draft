# Changelog

## 0.1.1 - 2026-07-13

- Fixed a macOS-specific unit-test failure caused by `/tmp` resolving to `/private/tmp`.
- Corrected Conda environment files for macOS-64 by removing the invalid
  `channel_priority` key and pinning PyArrow 24.
- Renamed the production Conda environment to `e3_discovery`.
- Added DIAMOND log-tail reporting to external-tool exceptions.
- Added an optional persistent output directory for the external DIAMOND
  end-to-end test to simplify debugging.

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
