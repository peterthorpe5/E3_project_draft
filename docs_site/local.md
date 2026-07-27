# Local operation

Local mode runs the same Snakefile in the foreground without Slurm:

```bash
./run_e3_pipeline.sh \
    --mode local \
    --config e3_end_to_end_workflow/config/my_run.yaml \
    --threads 8 \
    --resume
```

It is suitable for:

- synthetic end-to-end tests;
- development and debugging;
- small species panels on a workstation;
- users without a Slurm scheduler.

The YAML still controls per-stage thread, memory and runtime declarations. `--threads`
sets the total local CPU budget available to Snakemake.

## Dry-run

```bash
./run_e3_pipeline.sh \
    --mode local \
    --config e3_end_to_end_workflow/config/my_run.yaml \
    --threads 8 \
    --dry-run
```

## Limit a development run

```bash
./run_e3_pipeline.sh \
    --mode local \
    --config e3_end_to_end_workflow/config/my_run.yaml \
    --threads 8 \
    --stop-after 05_orthology \
    --resume
```

`--start-at` never bypasses a missing prerequisite. Successful stages are accepted only
when their manifest, configuration digest and output checksums remain valid.

Local mode has no detached status command because it remains attached to the foreground
process. Use the Slurm controller for long cluster runs that must survive logout.
