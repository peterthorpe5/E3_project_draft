# e3_end_to_end_workflow v0.9.3

Release date: 2026-07-27

## Slurm controller submission reliability

Version 0.9.3 separates active-controller duplicate protection from optional
historical accounting. A new controller submission now queries `squeue` only.
It therefore remains possible to resume an interrupted run when `slurmdbd` and
`sacct` are unavailable.

The launcher now:

- reports the submission preflight, run name, immutable configuration and
  scientific-job status backend before calling `sbatch`;
- permits resume only when the previous controller is absent from `squeue` or
  has a recognised terminal state;
- blocks duplicate submission when the prior controller is active;
- fails closed, with a visible diagnostic, when `squeue` fails or returns an
  unrecognised state;
- treats `sacct` as optional, time-bounded enrichment for `--status` only;
- bounds every `squeue`, `scontrol` and optional `sacct` query, with a
  configurable 15-second default;
- validates stale controller metadata before using its recorded job ID;
- reports scheduler rejection explicitly; and
- reports the accepted Slurm job ID if a later launcher operation fails.

Scientific child-job tracking remains explicitly configured to use `squeue`.
The supported executor remains
`snakemake-executor-plugin-slurm>=2.7.1,<3`, and a minimum `MinJobAge` of
120 seconds is required before submission. Dundee reports
`MinJobAge = 300 sec`, which satisfies this condition.

## Regression coverage

The Slurm launcher tests now cover:

- fresh submission;
- stale controller metadata with unavailable `sacct`;
- active-controller duplicate rejection;
- successful terminal-state resumption;
- failed and unrecognised `squeue` responses;
- bounded hanging and failed `sacct` status lookups;
- rejected `sbatch` calls; and
- malformed controller metadata.

No scientific schema, scoring rule, controlled input or production
configuration is changed by this release. Existing checksum-valid stage
outputs remain the restart authority.
