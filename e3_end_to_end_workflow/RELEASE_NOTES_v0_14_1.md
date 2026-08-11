# E3 end-to-end workflow v0.14.1

This patch release adds an optional controller-only Slurm quality-of-service
setting for long, restartable structural campaigns.

## Change

- `submit_e3_controller_slurm.sh --controller-qos NAME` adds `--qos NAME` to
  the Snakemake controller allocation only. Child scientific jobs continue to
  use their configured account and partition settings.
- The selected quality of service is recorded in `controller.slurm.tsv`.
- Scheduler names remain strictly validated and the default is unchanged when
  `--controller-qos` is omitted.

This supports the 1,972-group Milestone 2 structural campaign without changing
the scientific methods or allocating long-duration resources to every child
job.
