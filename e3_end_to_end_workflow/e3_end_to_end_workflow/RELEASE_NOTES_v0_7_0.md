# E3 end-to-end workflow v0.7.0

## Reproducible detached cluster execution

- Adds `submit_e3_end_to_end.sh` as the normal one-command cluster entry point.
- Keeps the lightweight Snakemake controller detached on the login node while scientific rules are
  submitted through the Slurm executor.
- Prevents nested controller execution inside a Slurm allocation by default.
- Prevents duplicate controllers for the same run with a persistent `flock` lock and records the
  controller PID, configuration and durable submission log.
- Adds named `--account` and `--partition` overrides while preserving stage-specific resource
  requests from the run YAML.
- Removes embedded Python from the foreground shell. Configuration path and run-root resolution use
  shell operations plus the tested `e3-workflow run-root` command.

## Optional three-dimensional pocket evidence

- Adds optional stage `09b_structural_alignment` without renumbering established stages 10 and 11.
- Integrates the separate `e3_structural_alignment` package, which uses US-align and TM-align global
  superpositions and then compares selected pocket coordinates in the same reference frame.
- Records global TM-scores, RMSD, transform files, pocket-centroid distances, symmetric
  nearest-neighbour overlap and transparent threshold decisions.
- Runs independent reference-to-member alignments concurrently up to the configured stage thread
  allocation.
- Publishes an explicit checksummed `skipped_optional` manifest when the stage is disabled.
- Keeps the existing sequence-aligned pocket-region result distinct from direct 3D pocket
  equivalence.
- Allows 3D evidence to be included in prioritisation only through the explicit
  `analysis.structural_alignment.use_for_prioritisation` switch. It defaults to `false` pending a
  reviewed multi-structure validation run.

## Compatibility and scaling

- Existing v0.6.0 run YAML files remain valid: an absent `09b_structural_alignment` section defaults
  to disabled and optional.
- The reviewed `Results_Feb26` archive remains the sole inherited 60-proteome OrthoFinder authority.
- The five-proteome configuration remains a bounded fresh-OrthoFinder validation and is not
  reclassified as the production panel.
- Future species remain manifest/configuration rows rather than shell-script constants.
