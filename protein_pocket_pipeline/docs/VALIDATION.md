# Validation record: 21 October 2026

## Completed

- 103 unit/output-contract tests passed with 97.43% combined statement/branch
  coverage after the final Python changes. The enforced minimum is 95%.
- The optional external integration test also passed with real fpocket 4.2.2
  (upstream source tag, commit `6c7c55dfdde6e8826f019e3ee4782e3a02dafecc`), P2Rank
  2.5.1 and OpenJDK 17. All 104 tests passed in the final integration run.
- A built wheel was installed into a separate directory and run from outside the
  source checkout. The run completed using the official P2Rank test structure
  `test_data/1fbl.pdb`, producing all four output formats.
- Real rescoring output uses names such as `pocket.4`. These were checked against
  original fpocket cavity IDs, rather than joined to newly assigned ranks.
- All normalised formats use the same records. Tests checked ranking, numeric
  types, missing values, failure states, primary keys and typed empty tables.
- The source distribution includes documentation, environment specification,
  optional Slurm wrapper, tests and the HTML resource. The wheel includes the
  runtime HTML resource and CLI entry point.
- Ruff lint/format checks, shell syntax and Git whitespace checks passed.
- All 11 workbook sheets were rendered and visually inspected. Descriptor widths,
  integer rank formats and the confidence-disabled guide were corrected.
- A real browser checked the offline report, table tabs, search, model selection,
  sorting and local download links, with no JavaScript errors. Desktop and narrow
  viewport layouts were inspected. Unassessed confidence is labelled explicitly.

Test environment: Linux, Python 3.12, Gemmi 0.7.5, DuckDB 1.5.6 and openpyxl 3.1.5.
The repository includes a Python 3.11/3.12 CI matrix; this record does not claim
that an unobserved remote CI run has passed.

## Limits of this validation

`1fbl.pdb` is an experimental MMP1 structure, not BRCA1 or an AlphaFold model.
The smoke run used confidence interpretation `none`. Artificial unit fixtures
check PDB/mmCIF mapping and AF3-style per-atom confidence, but are not biological
predictions. No denbi login or access to Maddy's 14 models was available here.
Those models still require their own run, model-confidence checks and structural
inspection. No pocket-binding accuracy, affinity or therapeutic conclusion has
been experimentally validated by these software checks.

The Conda environment is supplied but was not solved here: the real fpocket
binary was built from its pinned upstream source and the other dependencies were
installed separately. Native macOS and WSL2 execution were not tested here.
