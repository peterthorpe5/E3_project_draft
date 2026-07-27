# ARIA plant E3 project

This repository is a modular, restartable workflow for plant E3-ligase discovery,
orthology reconciliation, domain and expression evidence, ligandability analysis,
three-dimensional pocket comparison, transparent prioritisation and read-only reporting.

The main entry point is at the repository root:

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config e3_end_to_end_workflow/config/my_run.yaml \
    --max-jobs 4 \
    --account barton \
    --partition general \
    --resume
```

The Slurm mode submits the Snakemake controller as a batch job. The workflow continues
after logout and submits scientific stage jobs only when their dependencies are valid.
Workstations without Slurm use `--mode local`.

## What to read

- [Quick start](quick-start.md) for installation and first execution.
- [Master configuration](configuration.md) for every YAML section and tool parameter.
- [Complete fresh run](fresh-run.md) for a start-to-finish analysis without previous results.
- [Parameter sweeps](parameter-sweeps.md) for controlled threshold comparisons.
- [Component packages](packages.md) for standalone use.
- [Add new data](new-dataset.md) for a new species panel or evidence resource.

!!! warning
    Computational evidence does not establish E3 activity, binding, selectivity or
    degradation. Missing annotation or expression evidence must remain missing, not be
    converted to a biological negative.
