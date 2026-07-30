# Final-report evolutionary-group count hotfix

Date: 30 July 2026  
Affected run: `grant_aligned_structural_sensitivity_top100_v0_11_0_20260729`

## Failure

All scientific stages completed, but the final `generate-report` rule stopped
while reading:

```text
08_shortlist_gate/tables/evolutionary_candidate_group_ranking.parquet
```

The report emitted:

```text
ERROR: Could not count authoritative evolutionary groups
```

## Root cause

The Stage 08 file is the one-row-per-evolutionary-group authority. Its lead
cluster fields are deliberately prefixed with `lead_`, including:

```text
lead_grant_aligned_stringent_pass
```

The v0.11.0 report reader incorrectly queried the cluster-level field name
`grant_aligned_stringent_pass`, which is not present in this authority.
DuckDB therefore stopped at query binding before the consolidated report could
be written.

## Repair

- Query the correct `lead_grant_aligned_stringent_pass` field.
- Inspect the Parquet schema before counting.
- Accept validated native or textual Boolean representations.
- Reject missing or invalid stringent-pass values.
- Reject missing or empty evolutionary-group keys.
- Reject duplicate evolutionary-group rows.
- Include the underlying DuckDB diagnostic in future read failures.

The repair changes reporting only. It does not alter Stage 08 rankings,
structural results, pocket sensitivity results, thresholds or final scientific
decisions.

## Validation

- 223 workflow tests passed.
- Branch-aware workflow coverage: 90.62%.
- PEP 8, 100-character line limit and Google-style docstring checks passed.
- Snakemake lint passed.
- Complete synthetic DAG passed.
- Final no-op resume passed.
- 13 repository-level tests passed.
- Direct regression tests cover the production group-level field name, native
  and textual Boolean flags, missing columns, invalid flags, empty tables,
  empty group keys and duplicate group keys.
- A production-shape regression check returns the expected 1,972 evolutionary
  groups and 38 stringent pre-structure passes.

## Resume policy

Install the edited workflow package and resume the existing run in place with
the unchanged configuration. Do not delete the run root, force a stage or
change the run name. The completed scientific stages and structural shard
outputs remain the validated restart authority.
