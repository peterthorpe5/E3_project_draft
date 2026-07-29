# e3_end_to_end_workflow v0.11.0

## Milestone-1 sensitivity and release cycle

This release preserves the completed v0.10.2 50-group result as the stringent
primary analysis and adds a separate exploratory configuration:

`config/grant_aligned_structural_sensitivity_top100_v0_11_0_20260729.cluster.yaml`

The new profile:

- retains all 38 strict pre-structure passes and extends structural review to
  the ordered top 100 evolutionary groups;
- retains the independently selected rank-one pocket result;
- compares the selected reference pocket with the top five pockets in each
  member;
- requires US-align and TM-align to support the same candidate member pocket;
- reports alternative-pocket rescues separately from the primary result;
- publishes named druggability and top-k gate-sensitivity scenarios;
- exports canonical and ordered top-50 review tables for manual selection of
  up to ten experimental priorities;
- publishes ranked-pocket, sensitivity-comparison, member-summary and
  evolutionary-group-summary relations in DuckDB, Parquet and TSV formats;
- rebases temporary shard paths before provenance publication; and
- treats intentionally disabled optional stages as outside the configured
  release scope rather than as application-release blockers.

The sensitivity scenarios do not overwrite `grant_aligned_final_pass`.

## Quality evidence

The end-to-end suite enforces PEP 8, Google-style docstrings, direct unit and
integration tests, and at least 90% aggregate coverage. The Python application
suite remains above 95% coverage. The R Shiny package retains its testthat
suite; run it in the documented R environment before cluster release.
