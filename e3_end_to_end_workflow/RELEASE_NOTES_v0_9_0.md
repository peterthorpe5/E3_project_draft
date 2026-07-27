# e3_end_to_end_workflow v0.9.0

Release date: 2026-07-25

## Central configuration

- Adds schema version 2 while retaining schema-version-1 compatibility.
- Adds a validated `tools` registry containing executable, reviewed version, Conda environment
  and scalar component parameters.
- Exposes tool values to external argv templates through documented
  `tool_<tool>_<setting>` placeholders.
- Records the resolved central tool registry in every stage manifest.
- Adds `path_base` so generated configurations preserve the base file's relative paths.

## Parameter sensitivity

- Adds `prepare-sweep` for Cartesian or one-at-a-time parameter experiments.
- Permits existing paths below `analysis.` and `tools.` only.
- Adds deterministic run names, configuration checksums, parameter-set checksums and a
  `maximum_runs` expansion guard.
- Adds `compare-sweep`, which publishes run status, candidate-level sensitivity and candidate
  stability as TSV.
- Refuses incomplete comparisons unless `--allow-incomplete` is explicit.

## Complete fresh execution

- Adds `validate-fresh` and repository-root `run_e3_pipeline_fresh.sh`.
- Requires production mode, schema version 2, a central tool registry and all 13 stages.
- Rejects previous discovery, candidate, OrthoFinder, expression, domain-result and
  ligandability authorities.
- Requires generation commands for external scientific stages and rejects unresolved
  `CHANGE_ME` markers.
- Caps the root fresh launcher at ten concurrent scientific jobs.
- Uses the v0.8.0 Slurm-owned controller, so execution continues after logout.

## Documentation

- Adds a searchable MkDocs Material manual under `docs_site/`.
- Adds strict GitHub Pages build/deploy automation.
- Documents quick starts, configuration, fresh execution, Slurm/local operation, parameter
  sweeps, new datasets, every stage, every component package, outputs and troubleshooting.
- Updates the printable operator guide to v0.9.0.
