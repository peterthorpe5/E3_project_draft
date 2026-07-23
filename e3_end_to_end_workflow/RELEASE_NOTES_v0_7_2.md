# e3_end_to_end_workflow v0.7.2

- Adds `tables/e3_candidate_master_results.parquet`, one wide row per candidate
  group for the requested single-file hand-off.
- Retains all one-to-many evidence as normalised DuckDB relations.
- Adds a relation catalogue with app section, row granularity and source
  provenance.
- Extends the stage-11 hand-off with DuckDB and master-Parquet app
  configurations and checksums.
- Makes source-layout tests independent of editable installation by adding
  `src/` to `PYTHONPATH` in `run_tests.sh`.
- Resolves the previous 89%/90% quality-gate failure: all 111 tests pass at 90%
  branch-aware coverage.
