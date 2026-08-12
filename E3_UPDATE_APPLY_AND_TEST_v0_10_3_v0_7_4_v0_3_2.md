# E3 cumulative app update

Included versions:

- `E3_shiny_app` 0.10.3
- `e3_python_app` 0.7.4
- `e3_structural_alignment` 0.3.2

## What changed

- The Computational recommendations page has a focused slider for the inclusive
  final gate, `minimum_druggability_score >= selected_threshold`.
- The authoritative recorded 0.50 result remains unchanged; only an in-memory
  sensitivity pass list is recalculated.
- Horizontal box plots show retained selected-pocket scores and individual
  assessed members for lead clusters that pass every other fixed final gate.
- The former structure-viewer **Fit structure** action is now **Fit and centre**.
  It restores orientation and zoom and confirms the action visibly. Both apps
  also repair the old control when an existing portable review page is loaded.

## Apply

Commit or back up local work first, then extract this archive at the parent
directory containing the three project directories:

```bash
tar -xzf E3_app_cumulative_v0_10_3_v0_7_4_v0_3_2_final_gate_boxplot_viewer_fix_20260812.tar.gz
```

The archive contains source and tests only. It does not contain the integrated
DuckDB, Parquet results, structures or portable pocket-review data.

## Test the Python reporter

```bash
cd e3_python_app
python -m pip install --editable '.[dev]'
./run_tests.sh
```

The release gate in this environment passed 92 tests with 95% branch-aware
coverage.

## Test the Shiny reporter

```bash
cd E3_shiny_app
Rscript inst/scripts/check_dependencies.R
Rscript inst/scripts/run_tests.R
```

Run this native R gate on the target Mac or R environment; R was not available
in the packaging environment.

## Test the pocket-review generator

```bash
cd e3_structural_alignment
python -m pip install --editable '.[dev]'
./run_tests.sh
```

Python compilation, style and documentation checks passed for this package in
the packaging environment. Its complete test suite still needs the declared
Biopython development dependency in the target environment.
