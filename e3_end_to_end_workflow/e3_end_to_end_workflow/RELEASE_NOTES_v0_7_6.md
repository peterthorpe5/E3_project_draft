# e3_end_to_end_workflow v0.7.6

This patch corrects downstream orthology-table resolution after the v0.7.5 component-publication
fix.

## Root cause

The independently restartable orthology component intentionally retains internal stage products
for provenance. After v0.7.5 materialised the six portable files at the master stage-05 contract,
the completed stage therefore contained multiple same-named Parquet files:

```text
orthology/tables/
orthology/stages/03_map_candidates/tables/
orthology/stages/05_publish_portable_outputs/tables/
```

The domains, expression, prioritisation and final-integration adapters recursively searched the
whole stage directory and incorrectly required exactly one matching basename. The scientific
files were not ambiguous: only the public master-stage contract is authoritative downstream.

## Correction

- Resolves orthology tables only at the supported public contracts:
  `orthology/tables/<name>` or `tables/<name>`.
- Ignores component-internal `orthology/stages/...` provenance copies.
- Still fails closed if zero or two public contract files exist.
- Applies the same resolver to stages 06, 07, 08 and 10.
- Adds a regression with three same-named orthology Parquet files.

## Safe continuation

Completed stages, including stage 05, remain valid. Install v0.7.6 and resume the same run without
deleting its run directory. Snakemake will rerun failed downstream stages and retain completed
ones whose configuration and input checks remain valid.
