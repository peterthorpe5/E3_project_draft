# E3 end-to-end workflow v0.4.0

This is an in-place provenance, dependency and benchmarking upgrade to the existing master
workflow.

## OrthoFinder execution contract

- Added an exact Bioconda pin for OrthoFinder 2.5.5 to the package Conda environment.
- Retained Snakemake 9 and the Slurm executor plugin in the same self-contained environment.
- Replaced the stage-04 placeholder with the environment-owned `orthofinder` executable.
- Declared version-2 output checks for identifier maps, orthogroups, the root hierarchical grouping
  and the species tree.
- Recorded the project decision that the reviewed OrthoFinder 2.5.5 phylogeny was preferred for
  this dataset. This does not claim that version 2 is generally superior to version 3.

## Resource benchmarking

- Added sampled process-tree CPU, RSS, VMS, process, thread and I/O measurements to every stage.
- Added precise wall-clock and cumulative CPU timings, allocation efficiency, requested-resource
  utilisation and host/scheduler context.
- Added compressed time-series output plus TSV and JSON summaries within every stage directory.
- Added broader runner timings through checksum inventory, alongside the sampled scientific-stage
  scope and optional full Slurm job accounting.
- Added a final aggregation rule with per-stage and whole-workflow TSV summaries.
- Added best-effort Slurm `sacct` enrichment without making accounting availability a scientific
  completion dependency.
- Retained measurements for failed stage attempts under the run's `failed` directory.
- Made checksummed manifests and configuration-bound control tokens the restart authority and added
  post-success cleanup of transient Snakemake metadata to prevent stale incomplete markers.
- Added unit and synthetic end-to-end coverage for monitoring, serialisation and aggregation.

No inherited OrthoFinder outputs, existing run results or version-controlled data resources are
modified by this release.
