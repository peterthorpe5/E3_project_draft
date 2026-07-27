# e3_end_to_end_workflow v0.9.1

Release date: 2026-07-27

## Stage 07 Expression Atlas scalability repair

The failed production attempt ended immediately after the normal Stage 07 preamble and did not
publish any declared Stage 07 outputs. The retained log alone cannot distinguish a Slurm
out-of-memory kill from another external termination, because it contains no caught Python or
DuckDB exception. Static inspection nevertheless identified a concrete high-memory execution path
that required correction before another production attempt.

Stage 07 now:

- scans only checksum-validated `atlas_expression_long` partitions whose species occur among the
  selected orthology-group members;
- configures DuckDB to use the stage thread request, limit its managed memory to 75% of the Slurm
  memory request and spill larger intermediates inside the atomic stage working directory;
- reduces the full measurement table to candidate-relevant gene identities before the
  alias-to-gene join, avoiding the previous measurement-level join explosion;
- materialises the mapping and expression summary once each, then publishes Parquet and TSV from
  those bounded tables rather than re-running the analytical queries;
- removes the DuckDB spill directory only after successful query completion; and
- records total, selected and skipped partition counts plus the DuckDB resource limits in
  `qc/expression_validation.tsv`.

Checksum verification, exact identifier tiers, explicit ambiguous/unmapped states and the rule
that unavailable evidence is not a biological negative are unchanged.

## Installation provenance

The repository launcher no longer claims a hard-coded release independently of the imported
Python package. `e3-workflow diagnose-install` reports the active Python executable, CLI path,
distribution version, imported module path and expected source path. Every workflow launcher now
fails before submission if the installed command comes from another version or checkout.

The Slurm submitter performs this check with `conda run --name`, so it verifies the same Conda
environment that the controller job will use rather than whichever Python happens to be active on
the login node.

## Repository layout

Version 0.9.1 is intended to be installed from the true repository-root
`e3_end_to_end_workflow/` directory. The accidental nested `E3_project_draft/` upload is not a
second valid installation root.

## Safe continuation

Stages 00 through 05 of
`grant_aligned_reuse_q9sa03_only_v0_7_3_20260724` remain valid and must not be deleted. After
installing v0.9.1 from the correct source tree, resume the same immutable configuration. Snakemake
will rerun the failed unpublished Stage 07 work and retain checksum-valid completed prerequisites.

The exact Slurm terminal state should still be recovered with `sacct` and the Stage 07 worker log
where available; the scalability correction does not retrospectively prove that the previous job
was killed for memory.
