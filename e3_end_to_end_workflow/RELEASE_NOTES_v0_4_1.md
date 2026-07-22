# E3 end-to-end workflow v0.4.1

This is a restart-bookkeeping compatibility fix for the existing v0.4.0 workflow.

## Snakemake metadata handling

- Retained `drop-metadata: true` in both the local and Slurm profiles. Successful jobs therefore do
  not leave transient Snakemake metadata, while interrupted jobs remain subject to
  `rerun-incomplete`.
- Removed the redundant post-success `--cleanup-metadata` call. Snakemake 9 returns exit status 1
  when asked to clean records that have already been dropped, which caused the cluster quality run
  to stop after an otherwise successful 14-job synthetic workflow.
- Added a regression test requiring the wrapper to rely on the profile policy and forbidding a
  second metadata-cleanup call.

No scientific-stage code, stage dependencies, benchmark measurements, OrthoFinder settings,
controlled data assets or completed analysis outputs are changed by this release.
