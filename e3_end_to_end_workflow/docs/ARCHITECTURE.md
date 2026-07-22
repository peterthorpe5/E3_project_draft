# Architecture and release contract

## Purpose

The master package makes cross-package execution repeatable while keeping each scientific package
independent. A component may be upgraded without renaming old run outputs; the run configuration,
component logs and checksums identify exactly which implementation produced each release.

## Run directory

```text
<output_root>/<run_name>/
├── 00_inputs/
├── 01_prepared_proteomes/
├── 02_discovery/
├── 03_candidate_evidence/
├── 04_orthofinder/
├── 05_orthology/
├── 06_domains/
├── 07_expression/
├── 08_shortlist_gate/
├── 09_ligandability/
├── 10_integrated_resource/
├── 11_app_ready/
├── benchmark_summary/
├── failed/
├── superseded/
├── workflow_control/
└── workflow_logs/
```

Every stage directory contains `stage_manifest.json`, `logs/stage.log` and a `benchmark/` directory
with one-row TSV/JSON resource summaries plus a compressed process-tree time series. External tools
receive the temporary stage directory in both the `{stage_dir}` argv placeholder and
`E3_STAGE_DIR`. Publication uses an atomic rename on the output filesystem.

`benchmark_summary/` joins stage-monitor records to broader runner timestamps, output inventory and
optional Slurm accounting. It is created only after all twelve stage manifests exist.

`workflow_control/stage_tokens` contains persistent, configuration-digest-bound inputs to the
Snakemake rules. Refreshing one token is the controlled mechanism used by `--start-at` and
`--force-stage`; the changed input invalidates that stage and the DAG propagates the rerun to
affected downstream work.

Profiles use Snakemake's `drop-metadata` setting after successful jobs. This avoids stale
implementation metadata competing with the configuration-bound tokens and checksummed manifests.
An interrupted job's incomplete marker is still retained and is handled by `--rerun-incomplete`.
The shell wrapper also performs explicit completed-output metadata cleanup, but only after the
requested Snakemake target exits successfully.

## Dependency graph and concurrency

The workflow is not a serial list. After `01_prepared_proteomes`, `02_discovery` and
`04_orthofinder` are independent. `07_expression` depends only on validated controlled inputs.
Candidate evidence follows Discovery Engine, while orthology integration follows OrthoFinder. The
shortlist gate waits for candidate, orthology, domain and expression authorities. This makes safe
stage-level concurrency explicit while preserving every scientific join.

## Input manifest invariants

- `species_id` is unique and stable across releases.
- Every included FASTA is a regular file with a verified SHA-256.
- Seed accessions are unique and retain evidence type, source, E3 category, GO flags, organism,
  taxon, sequence checksum and inherited source-row provenance.
- The seed evidence authority is a deterministic gzip-compressed TSV derived from the full
  discovery-engine seed table; the sequence-bearing source table remains outside Git.
- Ligandability accessions require a human decision, reviewer, UTC time and rationale.
- A shortlist without at least one explicit `approve` decision is invalid.

## Production safety

`run.mode: production` changes validation behaviour. Every scientific stage other than controlled
input validation, the human shortlist gate and application handoff must provide a command as a YAML
argv list. Required stages cannot be disabled. A command's exit status and every declared non-empty
output is checked before publication. Before a downstream stage starts, every file in every
prerequisite manifest is checked again for size and SHA-256. Logs state the stage purpose, rationale,
dependencies, resources, expected outputs and external command output.

Resource monitoring begins before upstream checksum validation and stops after the stage command
and expected-output checks. The runner timestamps also cover the subsequent checksum inventory, so
the two wall times deliberately have different scopes. Slurm accounting can provide an independent
scheduled-job observation. Benchmark aggregation never edits a scientific stage or its manifest.

The production template deliberately contains `CHANGE_ME` commands because package-specific
adapters still need to be finalised against the exact cluster installations and run-specific paths.
This is preferable to silently embedding legacy paths or pretending a placeholder ran an analysis.

## Extension policy

A new species is a new row and FASTA checksum in `proteomes.tsv`, followed by a new immutable run
name. New evidence types should become new tables/views rather than columns injected into unrelated
authorities. DeepClust and OrthoFinder labels are always qualified by their source run identifiers.
