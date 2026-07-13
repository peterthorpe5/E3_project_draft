# Changelog

## 0.1.3 - 2026-07-13

- Fixed DIAMOND 2.2.3 exact-identity clustering failure: `--id` requires
  alignment traceback, which is incompatible with compositionally adjusted
  matrix modes.
- Added explicit `diamond.comp_based_stats` configuration and pass
  `--comp-based-stats` to both `deepclust` and `realign`.
- Production and end-to-end profiles now use mode `0`; legacy approximate
  reproduction uses mode `1`.
- Added defensive rejection of modes 2-6 for exact identity/realignment.
- Added focused diagnostic hints for the DIAMOND error
  `Traceback with adjusted matrix not supported`.
- Added unit and configuration regression tests for this compatibility rule.

## 0.1.2 - 2026-07-13

- Fixed DIAMOND 2.2.x command construction to use the supported `--db`
  option for `deepclust` and `realign`; `--database` is not accepted by the
  DIAMOND 2.2.3 binary.
- Updated the real-DIAMOND end-to-end test to use `--masking none` rather than
  the unsupported legacy value `0`.
- Added defensive validation for identity mode and masking values.
- Added regression tests that reject `--database` and invalid masking values.

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
