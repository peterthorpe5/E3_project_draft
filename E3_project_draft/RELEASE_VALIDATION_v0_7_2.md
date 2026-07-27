# PT_E3_6 reporting release validation

This record covers the coordinated reporting release:

- `e3_end_to_end_workflow` 0.7.2
- `e3_python_app` 0.2.0
- `E3_shiny_app` 0.4.0
- `e3_structural_alignment` 0.1.2

## Completed quality gates

| Component | Command | Result |
| --- | --- | --- |
| End-to-end workflow | `./run_tests.sh` | 111 passed; 90% branch-aware coverage |
| Python reporter | `./run_tests.sh` | 22 passed; 98% branch-aware coverage |
| Structural alignment | `./run_tests.sh` | 25 passed; 91% coverage |
| Shell entry points | Included in the component test scripts | Syntax and policy checks passed |
| DuckDB flexible source lifecycle | Attach, query, detach and reattach validation | Passed |
| Repository whitespace | `git diff --check` | Passed |

The end-to-end workflow result resolves the earlier `89%` versus `90%` coverage
failure. The workflow and structural test launchers now add their local `src`
directories to `PYTHONPATH`, so their test suites can run immediately after the
environment is created. An editable installation remains required to expose the
installed command-line programs.

## R Shiny validation required on a machine with R

The current development workspace does not provide `Rscript`, so the new Shiny
tests could not be executed here. Run these checks in the R application
environment before deployment:

```bash
cd ~/data/2026_E3_protac/E3_project_draft/E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

The R tests cover source selection, DuckDB and Parquet attachment, result-section
routing, section-specific column selection, configuration validation and the
generated user interface.

## Scientific interpretation

The application is a computational evidence resource for the grant:

- Milestone 1 asks whether candidate E3 ligases and their orthologues are
  sufficiently conserved and supported by the available expression evidence.
- Milestone 2 asks whether ligandable pockets occupy equivalent positions and
  retain local structural and chemical support across the selected species.
- Missing resources or unassessed stages remain distinct from biological
  negatives.
- Experimental MTF1 degradation is a downstream goal and is not presented as an
  observed result in these applications.

The single master Parquet is a candidate-level reporting table. Detailed
one-to-many evidence remains available as normalised DuckDB relations so that
orthogroup members, sequences, expression observations, pockets and residue-level
structural matches are not flattened or lost.
