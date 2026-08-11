# E3 v0.15.0 release handover

## Release outcome

This release integrates the v0.3.1 structure-guided chemistry results into the
Stage 10 DuckDB and both application interfaces. It also removes the obsolete
raw-expression sidebar and tabs from the R Shiny application.

## Current 1,972-group Milestone 2 run

The existing `run_dundee_full_universe_v0_3_0.sh` campaign remains a
transitional two-phase run. Do not resubmit it while controller 187058 is active.
The updated launcher recognises active controllers, reports failed-controller
logs before a safe resume and advances to chemistry only after upstream
structural completion.

## New-data readiness verdict

The workflow is not yet approved for a genuinely new expanded proteome panel.
The restart-safe launcher, DAG, ligandability, structural alignment, chemistry,
integration and app hand-off are implemented. Fresh discovery,
candidate-evidence construction, orthology output adaptation and fresh
Expression Atlas acquisition still require bounded real-data adapters and a
cross-stage smoke test.

`validate-fresh` now rejects unresolved placeholders anywhere in the YAML. A
successful syntactic preflight must not be presented as executable scientific
readiness.

## Validation completed in the build environment

- End-to-end workflow: 230 tests passed; one intentional skip.
- Structure-guided chemistry: 92 tests passed.
- Python application: 48 tests passed, including headless rendering.
- Python compilation, shell syntax and `git diff --check`: passed.
- R Shiny changes include testthat regressions, but R was unavailable in the
  build environment. Run the complete Shiny test suite in the declared
  `e3_shiny_app` conda environment before publishing.

## Application changes

- R Shiny uses a full-width navigation layout with no raw-expression sidebar.
- The four retired raw Expression Atlas tabs are removed.
- Integrated candidate expression evidence remains available.
- R Shiny and Python both expose a Computational chemistry section.
- Stage 10 imports chemistry target, pharmacophore, sensitivity, integrated
  candidate-evidence, fragment and optional ranked-pocket relations.
