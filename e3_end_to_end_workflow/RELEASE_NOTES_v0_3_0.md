# E3 end-to-end workflow v0.3.0

This release upgrades the existing master orchestration package; it does not replace or duplicate
the scientific logic in any component package.

## Changes

- The shell entry point remains the user-facing command and always launches the package Snakefile.
- Human-readable plan and stage logs explain what every stage does, why it is required, its
  prerequisites, requested resources and expected outputs.
- External component output is streamed to both the console and persistent stage logs.
- The serial stage chain is replaced by the scientific dependency graph. Discovery Engine, fresh
  OrthoFinder and expression work can run concurrently when resources permit.
- Each stage declares threads, memory and runtime for resource-aware local or Slurm scheduling.
- `--resume`, `--start-at`, `--stop-after`, `--force-stage`, `--threads` and `--max-jobs` are formal
  named shell options.
- Configuration-bound stage tokens provide a controlled rerun mechanism without deleting results.
- Multi-prerequisite manifests are revalidated by size and SHA-256 before downstream joins.
- Unit, synthetic end-to-end, shell syntax, style, documentation and coverage gates are retained.
