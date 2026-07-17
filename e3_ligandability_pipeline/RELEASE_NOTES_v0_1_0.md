# Release notes: v0.1.0

Initial production release of the ARIA plant E3 ligandability workflow.

## Added

- safe AlphaFold metadata selection and asset materialisation;
- direct model-derived pLDDT calculation;
- explicit model/API quality comparison;
- FPocket plus P2Rank rescoring command orchestration;
- atomic external-tool output publication;
- FPocket/P2Rank parsers;
- label/author residue-number mapping with ambiguity detection;
- conservative pocket-confidence calculations;
- TSV, Parquet and materialised DuckDB outputs;
- QC and full run provenance;
- pinned FPocket 4.2.2 from the recovered inherited environment;
- required P2Rank 2.5.1 preflight for inherited comparability;
- local/Conda and Slurm shell wrappers;
- inherited model-level regression command;
- frozen legacy scripts and checksums;
- comprehensive unit, integration, command-line and release-contract tests.

## Scientific release state

The software release is tested with synthetic fixtures and fake external
executables. Real FPocket/P2Rank cluster validation remains deliberately
pending. The next action is controlled regression against the inherited test
set followed by a one- or two-model smoke run. No full inherited collection
rerun is recommended.
