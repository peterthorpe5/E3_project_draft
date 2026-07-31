# v0.3.1 Slurm path hotfix — 31 July 2026

## Summary

The pocket-review Slurm submitter now passes the absolute package root to the
worker explicitly. This prevents Slurm's copied worker script from incorrectly
resolving `run_e3_pocket_review.sh` beneath `/var/spool/slurmd`.

## Scope

- No scientific calculations, ranking logic, thresholds or report contents
  changed.
- Existing completed end-to-end runs remain valid and do not need to be rerun.
- A failed pocket-review report job can be resubmitted safely with `--resume`.

## Validation

The regression test executes a copy of the worker from a simulated
`/var/spool/slurmd` directory and verifies that it invokes the runner from the
explicit package root.
