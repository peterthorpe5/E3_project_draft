# E3 project release validation v0.9.2

Release date: 2026-07-27

This repair release passes the validated absolute workflow source root into the internal Slurm
controller body. It therefore remains correct when Slurm executes a temporary batch-script copy
from `/var/spool/slurmd`.

Validation completed:

- 178 master-package tests passed;
- 90% branch-aware coverage;
- 12 repository-root launcher and documentation tests passed;
- a regression test executed the controller from a simulated Slurm spool directory and verified
  that it called the runner from the supplied source tree;
- the submitted `sbatch` argument contract records the absolute source root;
- Python compilation, PEP 8 and Google-style docstring checks passed;
- shell syntax and no-embedded-Python checks passed;
- Snakemake lint passed;
- the complete 16-job synthetic DAG completed, including Stage 07, consolidated benchmarks and
  the final HTML report;
- the post-run dry run reported no work remaining; and
- the recovered run-specific YAML is byte-identical to the preserved file with raw SHA-256
  `8b6ba4757fa211f296966171ba0053c1be7035db1f9653816cc1e1dc8649dea4`.

The production Dundee run remains the live-environment acceptance test. Controller job `62079`
failed before Snakemake or a scientific child job started, so resuming does not require deleting
or forcing any completed scientific stage.
