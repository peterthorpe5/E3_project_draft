# E3 project release validation v0.9.1

Release date: 2026-07-27

This repair release bounds Stage 07 Expression Atlas processing, verifies the active installed
source before local or Slurm execution, and removes the accidental nested repository copy.

Validation completed:

- 177 master-package tests passed;
- 90% branch-aware coverage;
- 12 repository-root launcher and documentation tests passed;
- focused tests exercised selected-species partition pruning, a species with no matching
  expression partition, DuckDB memory/spill settings and rejection of an installed v0.7.6
  command;
- the 16-job synthetic Snakemake DAG completed, including Stage 07, consolidated benchmarks and
  the final HTML report;
- the post-run dry run reported no work remaining;
- Python compilation, PEP 8 and Google-style docstring checks passed;
- shell syntax, named-interface and no-embedded-Python checks passed;
- Snakemake lint and workflow configuration validation passed;
- the MkDocs site built with `--strict`;
- the repository contained one source root and no tracked macOS `.DS_Store` files; and
- the diagnostic command matched source, import and distribution version 0.9.1.

The production run and the retained 24 July scheduler state were not available in this
environment. Therefore:

- the previous failure's exact Slurm terminal state remains unconfirmed until its `sacct` row and
  worker log are recovered; and
- successful completion of the real Expression Atlas Stage 07 and the remaining Dundee DAG is
  the live-environment acceptance test.

The supplied log is consistent with abrupt external termination but does not, by itself, prove an
out-of-memory kill. The repaired high-memory code path was independently established by static
inspection and is covered by bounded synthetic tests.
