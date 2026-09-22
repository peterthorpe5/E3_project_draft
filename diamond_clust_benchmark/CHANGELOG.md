# Changelog

## 0.1.1 - 2026-09-22

- Replace the large sentinel-membership self-joins with staged, bounded-memory
  DuckDB queries.
- Add explicit two-thread DuckDB execution, disabled insertion-order retention
  and persistent-filesystem spill space for full 1KP quality comparisons.
- Add a report-only Slurm recovery launcher so completed DIAMOND observations
  are never rerun after a reporting failure.
- Correct the benchmark launcher's Dundee partition default to `barton`.

## 0.1.0 - 2026-09-21

- Add isolated DIAMOND 2.2.3 versus 2.2.8 clustering benchmark matrix.
- Add Snakemake and Dundee Slurm launchers with sequential case execution.
- Add process-tree wall/CPU/memory/I/O measurement and immutable provenance.
- Add scalable DuckDB membership concordance and E3 sentinel guardrails.
- Add TSV/JSON summaries and a self-contained HTML decision report.
- Add external-executable integration tests and frozen protocol documentation.
