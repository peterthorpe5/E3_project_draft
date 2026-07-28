# e3_end_to_end_workflow v0.10.0

## Structural-completion decision release

Version 0.10.0 adds the production path from the completed v0.9.7
pre-structure resource to an auditable structural and decision-ready result.

### Scientific contract

- Preserve the completed parent run and checksum-validate every imported Stage
  02-08 output.
- Rank distinct primary OrthoFinder evolutionary groups while retaining every
  contributing DeepClust cluster in a separate relation.
- Select one deterministic, likely-full-length representative per target
  species and evolutionary group, with every alternative retained in an audit
  table.
- Assess at most 50 evolutionary groups and 600 primary structures.
- Keep three-dimensional evidence out of score reweighting until its thresholds
  have been reviewed; report it as an explicit final support/eligibility gate.
- Publish a top-20 computational review shortlist so project leads can select
  ten experimental priorities.

### Cluster execution

- Scatter ligandability into at most 600 independent four-core tasks.
- Scatter US-align/TM-align analysis into at most 50 independent four-core
  group tasks.
- Use Snakemake's global `--max-jobs 100` limit to cap concurrent cluster work.
- Retain checksum-bound task markers and a hidden work cache so successful
  shards survive controller or aggregate-stage retries.

### Final reporting

- Add `10_integrated_resource/final_results` as the explicit decision folder.
- Add a formatted multi-sheet Excel workbook with frozen header rows, filters,
  readable widths, metadata, settings and interpretation guidance.
- Publish one-row-per-evolutionary-group, top-20, strict prediction,
  DeepClust-contributor and exclusion-audit tables in TSV and Parquet.
- Add a dedicated Final recommendations section to both the R Shiny and Python
  applications while retaining the complete normalised result browser.

### Validation

- Production structural configuration loads with 600 ligandability slots, 50
  structural slots and a top-20 decision limit.
- Parent checksum failures, shard resume state, union aggregation, nested
  offline browser assets and component-process failures have dedicated
  regressions.
- The complete production structural Snakemake scatter DAG builds in dry-run.
- The standard 16-job synthetic DAG, controlled rerun, resume and final no-op
  remain release gates.
