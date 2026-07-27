# E3 end-to-end workflow v0.2.0

This release fixes the initial package quality gates and establishes the controlled known-E3 seed
evidence contract.

## Changes

- Removed all blank lines after function docstrings that triggered `pydocstyle D202`.
- Removed surplus end-of-file blank lines that triggered `pycodestyle W391`.
- Added transparent reading and writing of `.tsv.gz` manifests.
- Added `e3-workflow build-seed-evidence` with named options, deterministic gzip and provenance.
- Added the expanded seed-evidence schema and validation.
- Updated the production template to consume `data/known_e3_seed_evidence.tsv.gz`.
- Added `nodefaults` to prevent the cluster's legacy `R` channel contaminating environment solves.
- Corrected an unreachable test defect exposed after the style gates were repaired.
- Added unit and CLI tests for seed evidence and compressed TSV handling.

The external production-stage adapters remain intentionally unconfigured and continue to fail
closed. This release is suitable for package testing and input preparation, not yet for launching
the genuine full scientific pipeline.
