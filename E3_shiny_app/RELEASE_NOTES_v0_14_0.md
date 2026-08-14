# ARIA plant E3 Shiny reporter v0.14.0

## Direct pre-structure top-N HOG list

The new **Pre-structure ranked HOGs** tab provides the team's requested ungated
top-200 analysis set directly. It selects one row per root-level `N0.HOG…` by
the authoritative recorded `prestructure_evolutionary_group_rank`, or the
equivalent `evolutionary_group_rank` when that is the published field. It does
not accept the distinct cluster-level `computational_rank` and applies no
target-species, mandatory-species, domain, expression, pocket, druggability or
structural gate.

The count is adjustable within the global row cap. A literal search filters
only within the selected top-N rows and never recalculates their ranks. The
display and paired TSV/Excel downloads retain all source annotations plus
available human and Arabidopsis HOG representatives.

## Contextual tab help

All 25 top-level tabs now begin with a collapsed **❓ How to use this tab** box.
Each entry explains the principal controls, evidence boundary and a relevant
interpretation caution. The shared catalogue and UI coverage are tested so new
tabs must deliberately add their own guidance.

## Defensive behaviour and validation

The new module reports unavailable rank fields and query errors in the UI
without inventing a fallback biological result. Focused tests cover source
selection, query bounds, root-HOG filtering, absence of gate filtering,
representative annotation, retained recorded ranks, summary edge cases,
downloads and complete help coverage.

Run the complete release gate before publishing:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The two `test_script_utils.R` skips remain expected when the R session does not
provide a `--file` argument. Any actual failure blocks release.
