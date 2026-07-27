# e3_end_to_end_workflow v0.9.5

Release date: 2026-07-27

## Stale Slurm controller metadata

Version 0.9.5 corrects the controller duplicate guard for a normal Dundee
Slurm response after an earlier job has aged out of the live queue.

`squeue --jobs JOB_ID` can return a non-zero exit status with:

```text
slurm_load_jobs error: Invalid job id specified
```

This response means that the recorded controller job is no longer present in
the live queue. The launcher now treats this specific diagnostic as
`NOT_IN_QUEUE` and permits a checksum-safe resume. Other non-zero responses,
timeouts and unrecognised states remain fatal, so a genuine scheduler outage
cannot permit a duplicate controller.

## Cluster-portable tests

Routine tests no longer require scheduler subprocesses to complete within a
five-second wall-clock assertion. The Dundee cluster can exceed that threshold
because of scheduler and shared-filesystem latency even when the configured
hard timeout behaves correctly. Regression coverage continues to verify the
required exit status, diagnostics, refusal behaviour and accepted stale-job
path.

No scientific schema, scoring rule, controlled input or production
configuration is changed. Existing checksum-valid stage outputs remain the
restart authority.
