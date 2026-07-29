# Release validation: v0.11.0

Validation date: 2026-07-29

## Scope

This release adds the Milestone 1 closure and sensitivity workflow:

- an immutable 100-evolutionary-group exploratory profile;
- reference-pocket-versus-top-5-member-pocket sensitivity analysis;
- explicit agreement between US-align and TM-align on the same member pocket;
- unchanged strict one-pocket conclusions alongside separate sensitivity
  conclusions;
- named final-gate sensitivity scenarios;
- ordered top-50 review outputs;
- corrected evolutionary-group, DeepClust-cluster and application-release
  reporting; and
- updated Python and Shiny relation discovery for the new outputs.

## Automated validation

| Component | Result | Line coverage |
|---|---:|---:|
| `e3_end_to_end_workflow` | 202 passed, 1 skipped | 90% |
| `e3_structural_alignment` | 29 passed | 90% |
| `e3_python_app` | 22 passed | 98% |

The Python suites meet the release minimum of 90% line coverage. Tests exercise
the new configuration, defensive validation, top-k pocket matching, two-aligner
consensus, integration, reporting and application relation discovery.

The validation commands were:

```bash
cd e3_end_to_end_workflow
../.venv/bin/python -m pytest

cd ../e3_structural_alignment
../.venv/bin/python -m pytest

cd ../e3_python_app
../.venv/bin/python -m pytest
```

Shell syntax and patch hygiene also passed:

```bash
bash -n e3_structural_alignment/run_e3_structural_alignment.sh
git diff --check
```

## Code-quality criteria

New and changed Python functions use type hints, Google-style docstrings,
defensive input and schema validation, and module loggers at decision,
fallback and failure boundaries. Code follows PEP 8 and is covered by focused
unit tests plus integration tests.

## Outstanding runtime validation

`Rscript` is not installed in the current validation environment. The Shiny
source and test fixtures have been updated, but its runtime suite must be
executed in the release R environment before formal application sign-off:

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

This pending R check is an application-release condition; it does not invalidate
the completed Python workflow or structural-analysis test results.

## Scientific interpretation boundary

The completed 50-group production result remains immutable. The new top-k and
gate analyses are explicitly labelled sensitivity analyses, and the 100-group
configuration is a separate exploratory profile. A sensitivity pass cannot
silently overwrite the strict one-pocket result.

