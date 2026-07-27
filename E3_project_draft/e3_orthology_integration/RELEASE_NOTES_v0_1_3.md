# E3 orthology integration v0.1.3

## Resolved defects

- Replaced invalid standard-logging placeholders such as `%,d` with safely formatted grouped
  counts. Progress messages such as `1,250,000 records` no longer emit logging tracebacks.
- Removed an inherited `SLURM_CPUS_PER_TASK` value before calling `sbatch`. This matters when a
  submission is made from an interactive Slurm job with a different CPU allocation.
- Added a compute-node guard that compares the independently exported request with
  `SLURM_CPUS_PER_TASK` and fails before analysis if they differ.
- Made the submitter infer pipeline `--threads` from `--cpus-per-task` when omitted and reject an
  explicit mismatch.
- Preserved a YAML-configured thread value when local execution omits the CLI override.
- Connected `execution.threads` to the PyArrow compute and I/O thread pools.

## Scientific impact

The completed Results_Feb26 outputs from v0.1.2 remain valid. This release changes logging and
resource control only; identifier parsing, mapping tiers, orthogroup membership, regression checks
and publication contracts are unchanged.

## Verification target

The complete configured suite contains 42 tests and retains the 95% branch-aware coverage gate.
