# Slurm operation

## Controller and child jobs

Slurm mode has two layers:

1. a small controller job runs Snakemake;
2. Snakemake submits scientific stage jobs through its Slurm executor.

The controller defaults to one CPU, 4,000 MiB and three days. Its walltime must cover the
whole orchestration period. Scientific resources come from each stage in the master YAML.

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config /absolute/path/to/run.yaml \
    --max-jobs 4 \
    --account barton \
    --partition general \
    --resume
```

The launcher records the controller job ID below:

```text
RUN_ROOT/workflow_control/controller.slurm.tsv
```

It also uses a per-run submission lock. A second active controller for the same run is
rejected.

## Monitoring

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config /absolute/path/to/run.yaml \
    --status
```

Use the reported controller job ID with:

```bash
squeue --jobs JOB_ID
sacct --jobs JOB_ID --format=JobID,State,Elapsed,MaxRSS,ExitCode
```

Persistent logs are under:

```text
RUN_ROOT/workflow_logs/
```

Follow a stage log with `tail -F`, which continues if the file is replaced:

```bash
tail -F RUN_ROOT/workflow_logs/07_expression.snakemake.log
```

The `.snakemake/slurm_logs` tree belongs to the executor and may be transient.

## Concurrency

`--max-jobs` is the maximum number of scientific child jobs submitted concurrently by one
controller. The DAG may run independent branches such as domains and expression in
parallel.

For the Dundee cluster, keep any single stage within the three-day maximum. Split longer
component work into restartable internal stages rather than requesting an invalid
walltime.

## Conda

The submitted controller uses `conda run`; it does not assume that `conda activate` works
inside a non-interactive batch shell. Use `--conda-environment` and
`--conda-executable` on the controller launcher when the defaults are unsuitable.

## Controlled reruns

```bash
./run_e3_pipeline.sh \
    --mode slurm \
    --config /absolute/path/to/run.yaml \
    --start-at 07_expression \
    --resume
```

Use `--force-stage` only for an intentional same-configuration refresh. A changed
threshold or input needs a new run configuration.
