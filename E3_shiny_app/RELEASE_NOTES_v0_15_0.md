# ARIA plant E3 Shiny reporter v0.15.0

## Complete enriched HOG results

The **All results** tab now defaults to an enriched one-row-per-root-HOG result.
Its first selectable fields are HOG ID, canonical pre-structure and
post-structure ranks, human representatives and Arabidopsis representatives.
It also exposes membership/species summaries and every original field from the
strongest available HOG-linked ranking relation.

A separate member-detail result includes every source
`hierarchical_membership` field under an explicit `member_` name and repeats the
complete HOG-level ranking and representative context. Membership-only and
ranking-only HOGs remain visible and carry explicit source-availability flags.

The original raw DuckDB relations are unchanged and remain selectable for exact
source audit. The UI explains whether **Select all fields** refers to an
enriched joined result or one raw relation, and both routes preserve bounded TSV
and formatted Excel downloads.

Run the complete release gate before publishing:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when no `--file` argument is
available. Any actual failure blocks release.
