# E3 end-to-end workflow v0.5.0

This feature release adds verbose, checksum-bound HTML reporting to the existing orchestration
package. It does not replace component packages or alter the scientific dependency graph.

## Reporting

- Added one self-contained HTML report to every successfully published stage.
- Added a consolidated full-run HTML report after all twelve stages and benchmark aggregation.
- Added explicit purpose, rationale, supported interpretation and scientific limitation text for
  every stage.
- Added exact external argument vectors and an append-only shell-to-Snakemake invocation history.
- Added input paths/checksums, output checksums, validation state, logs and software/run provenance.
- Added embedded SVG charts for per-stage CPU/RSS time series and run-level wall time, CPU time,
  peak stage RSS and output-size comparisons.
- Added bounded, read-only result summaries for TSV, compressed TSV, FASTA, compressed FASTA,
  Parquet, DuckDB, SQLite, JSON and text outputs.
- Added a report manifest and completion TSV, with atomic publication and superseded/failed report
  retention.

## Workflow contract

- Stage reports are generated only after declared outputs validate and are themselves checksummed in
  `stage_manifest.json`.
- The complete report requires all stage reports plus the completed benchmark authority.
- Partial `--stop-after` runs publish reports only for completed stages and never a false full-run
  report.
- Added `reporting.preview_rows`, `reporting.max_table_columns` and
  `reporting.max_chart_items` controls.
- Added DuckDB 1.4–1.x as a package dependency for read-only Parquet and DuckDB inspection.
- Added a full-run-only compatibility cleanup for stale Snakemake 9 multi-output markers; partial,
  failed and interrupted runs never reach the cleanup boundary.
- Preserved OrthoFinder 2.5.5, restart tokens, atomic stage publication, safe concurrency and all
  controlled `data/` assets.

## Verification

- 74 tests pass.
- Branch-aware coverage remains 95%.
- PEP 8, PEP 257, shell syntax and Python compilation pass.
- Snakemake lint passes.
- The 15-job concurrent synthetic DAG passes, including twelve stage reports, benchmark aggregation
  and the complete report.
- Controlled OrthoFinder-to-orthology rerun, downstream resume and final clean dry-run pass.
