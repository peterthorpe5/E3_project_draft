# e3_structural_alignment v0.1.2

- `run_tests.sh` now resolves the repository's `src/` package automatically.
- A newly created conda environment can run the tests without first failing with
  `ModuleNotFoundError: No module named 'e3structalign'`.
- The editable installation remains the supported way to publish the
  `e3-structure-align` command-line entry point.
- All 25 structural-alignment tests pass at 91% branch-aware coverage.
