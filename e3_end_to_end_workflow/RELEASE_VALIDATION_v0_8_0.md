# E3 project root orchestration release validation v0.8.0

Date: 24 July 2026

## Scope

This release adds repository-root execution, a Slurm-owned Snakemake controller, non-Slurm local
execution documentation and the cross-package operator guide. Scientific transformations remain
those validated in `e3_end_to_end_workflow` v0.7.6.

## Automated checks

- repository-root launcher: 6 tests passed;
- end-to-end package: 132 tests passed;
- branch-aware end-to-end package coverage: 90%;
- PEP 8 check: passed at 100 characters;
- Google/PEP 257 docstring check: passed;
- Python compilation: passed;
- shell syntax: passed for all updated entry points;
- controller submission regression: passed with fake `sbatch`, `squeue` and `sacct`;
- active-controller duplicate guard: passed;
- Dundee 72-hour fresh-template stage limit: passed;
- package/root version consistency: passed;
- whitespace/archive integrity: passed.

## PDF checks

- source: repository-root `README.md`;
- format: A4;
- pages: 15;
- Poppler render: all pages rendered successfully;
- visual inspection: cover, contents, code blocks, tables, page breaks, headers and footers passed;
- text extraction: key headings and commands present;
- no clipped or overlapping content observed.

## Operational boundary

The new controller mode requires a cluster that permits `sbatch` from a compute allocation. This is
the standard model assumed for the Dundee Slurm deployment. The controller has its own walltime; if
that allocation ends, the same immutable run can be submitted again with `--resume`.

The legacy detached login-node launcher remains present but is not the recommended Dundee mode.

## Release contents

- `run_e3_pipeline.sh`;
- `run_repository_tests.sh`;
- repository-root `README.md`;
- `docs/E3_PROJECT_OPERATOR_GUIDE_v0_8_0.pdf`;
- updated `REPOSITORY_FILE_GUIDE.md`;
- `e3_end_to_end_workflow` v0.8.0; and
- unchanged component packages included for a coherent repository-root update.
