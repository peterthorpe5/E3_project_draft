# e3_end_to_end_workflow v0.7.4

This patch fixes the bounded Slurm-launch failure observed on 24 July 2026.

## Root cause

The launcher appended the target produced by `--stop-after` after Snakemake's
`--default-resources` option. That option accepts a variable-length sequence of `NAME=VALUE`
expressions. With no later option to terminate the sequence, Snakemake interpreted the stage
manifest target as a fifth resource expression and raised:

```text
ValueError: dictionary update sequence element #4 has length 1; 2 is required
```

The controller therefore failed before building the DAG or submitting a scientific Slurm job.

## Correction

- Places an explicit workflow target before the variable-length default-resource arguments.
- Retains command-line `--account` and `--partition` overrides for Slurm execution.
- Adds a behavioural regression test that runs the shell wrapper with fake executables and verifies
  the exact bounded-target and resource argument order.
- Keeps the v0.7.3 production stage-00 report correction unchanged.

## Safe continuation

The failed v0.7.3 start did not submit a scientific job. After installing v0.7.4, the same immutable
configuration and run name can be resumed with `--resume --stop-after 05_orthology`.
