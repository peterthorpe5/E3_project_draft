# e3_end_to_end_workflow v0.9.4

Release date: 2026-07-27

## Slurm query portability

Version 0.9.4 corrects two regressions found during the first Dundee cluster
acceptance run of v0.9.3.

Scheduler queries now use a hard timeout that also terminates stubborn child
processes. This keeps the documented query limit valid across the different GNU
coreutils and process behaviours observed on the development system and the
Dundee cluster.

The `MinJobAge` query is now treated according to its actual purpose:

- `squeue` and `sbatch` remain mandatory for safe duplicate detection and
  controller submission;
- an observed `MinJobAge` below 120 seconds remains a fatal compatibility
  error;
- an unavailable, timed-out or unparsable `scontrol` response produces a
  visible warning but does not block submission; and
- active-controller state still fails closed whenever `squeue` itself cannot
  return a trustworthy result.

The submission path no longer reports the generic unexpected-error trap after
an already diagnosed compatibility failure.

## Regression coverage

The Slurm launcher tests now cover:

- a scheduler child process that survives `TERM`;
- hard timeouts for `squeue`, optional `sacct` and advisory `scontrol` queries;
- successful submission when `scontrol` fails or times out;
- continued rejection of a successfully observed low `MinJobAge`;
- absence of misleading unexpected-error diagnostics for anticipated failures;
  and
- all v0.9.3 duplicate, stale-metadata and scheduler-rejection cases.

No scientific schema, scoring rule, controlled input or production
configuration is changed. Existing checksum-valid stage outputs remain the
restart authority.
