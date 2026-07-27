# E3 project release validation v0.9.0

Release date: 2026-07-25

This release adds central tool configuration, immutable parameter-sensitivity experiments,
strict clean-room execution and searchable GitHub Pages documentation.

Validation completed:

- 172 master-package tests passed;
- 90% branch-aware coverage;
- 12 repository-root launcher and documentation tests passed;
- the 16-job synthetic Snakemake DAG completed and its final dry run was empty;
- Python compilation, PEP 8 and Google-style docstring checks passed;
- shell syntax and no-embedded-Python checks passed;
- all workflow YAML files and the parameter-sweep specification validated;
- the MkDocs site built with `--strict`;
- all 15 A4 PDF pages rendered and passed visual inspection;
- all release interfaces reported version 0.9.0.

The first real Dundee `sbatch` clean-room controller submission remains a live-environment
acceptance test and must be recorded separately after the release is installed on the cluster.
