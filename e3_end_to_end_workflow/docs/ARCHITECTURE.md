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
├── 09b_structural_alignment/
├── 10_integrated_resource/
├── 11_app_ready/
├── benchmark_summary/
├── reports/
├── failed/
├── superseded/
├── workflow_control/
└── workflow_logs/
```

Every stage directory contains `stage_manifest.json`, `logs/stage.log`,
`report/stage_report.html` and a `benchmark/` directory with one-row TSV/JSON resource summaries
plus a compressed process-tree time series. External tools receive the temporary stage directory in
both the `{stage_dir}` argv placeholder and `E3_STAGE_DIR`. Publication uses an atomic rename on the
output filesystem. The report is generated inside the temporary directory and is itself included in
the manifest checksum inventory.

`benchmark_summary/` joins stage-monitor records to broader runner timestamps, output inventory and
optional Slurm accounting. It is created after every stage in the configured DAG reaches a terminal
completed or explicitly skipped state.

`reports/` contains the self-contained full-run HTML, completion TSV and checksum manifest. Its
Snakemake rule requires all thirteen stage reports and the completed benchmark aggregate. Report
publication uses a temporary run directory and atomic rename; a previous report is retained under
`superseded/` when regenerated.

`workflow_control/stage_tokens` contains persistent, configuration-digest-bound inputs to the
Snakemake rules. Refreshing one token is the controlled mechanism used by `--start-at` and
`--force-stage`; the changed input invalidates that stage and the DAG propagates the rerun to
affected downstream work.

Profiles use Snakemake's `drop-metadata` setting after successful jobs. This avoids stale
implementation metadata competing with the configuration-bound tokens and checksummed manifests.
An interrupted stage's incomplete marker is still retained and is handled by
`--rerun-incomplete`. After the complete default target succeeds, the shell wrapper calls
`--cleanup-metadata` for all declared, successfully published outputs. Snakemake 9 can retain a
multi-output rule's incomplete markers even after successful atomic publication; the wrapper
tolerates only the expected absent-metadata response and treats any traceback, filesystem or
permission failure as fatal. Partial targets and failed or interrupted DAGs never reach this step.

## Dependency graph and concurrency

The workflow is not a fixed-size serial list. In fresh mode, Discovery and OrthoFinder can run
concurrently after proteome preparation. Candidate evidence follows Discovery; orthology
integration follows candidate evidence and OrthoFinder. Domain download and expression mapping both
use the full membership of the selected run-specific groups. They converge at the computational
prioritisation stage. A reviewed result can replace any generation branch through `evidence_mode:
reuse` without changing the downstream table contract.

The optional `09b_structural_alignment` stage follows ligandability. When enabled, the separate
`e3_structural_alignment` package selects a deterministic best-evidence reference per candidate
group, runs independent US-align and TM-align superpositions concurrently within the allocated
node, and compares selected pocket C-alpha coordinates in the common reference frame. When
disabled, it
publishes a normal checksummed `skipped_optional` stage manifest. Integration therefore remains
complete but labels 3D evidence as `NOT_ASSESSED`; it never converts a configured omission into a
negative structural result.

## Input manifest invariants

- `species_id` is unique and stable across releases.
- `species_id` is safe for deterministic filenames and contains only letters, numbers, dots,
  underscores and hyphens.
- Every included FASTA is a regular file with a verified SHA-256.
- Native stage 01 checks FASTA structure, non-empty records and unique primary identifiers, then
  copies exact bytes into the isolated run and verifies the copied SHA-256.
- Seed accessions are unique and retain evidence type, source, E3 category, GO flags, organism,
  taxon, sequence checksum and inherited source-row provenance.
- The seed evidence authority is a deterministic gzip-compressed TSV derived from the full
  discovery-engine seed table; the sequence-bearing source table remains outside Git.
- Target and mandatory species panels are configuration lists, not compiled constants.
- Missing domain, expression or structural resources retain explicit unavailable states and are
  excluded from biological-negative denominators.
- Disabled 3D structural alignment is an explicit analysis state, not a failed stage and not
  evidence that pockets differ.
- The stage-08 human-review TSV is an output template; the computational ranking does not claim
  human approval.

## Production safety

`run.mode: production` changes validation behaviour. Every enabled stage must provide either a
documented native implementation or a command as a YAML argv list. Required stages cannot be
disabled. Every stage also declares whether it validates, prepares, reuses, downloads, derives or
generates evidence. A command's exit status and every declared non-empty output is checked before
publication. Before a downstream stage starts, every file in every
prerequisite manifest is checked again for size and SHA-256. Logs state the stage purpose, rationale,
dependencies, resources, expected outputs and external command output.

Resource monitoring begins before upstream checksum validation and stops after the stage command
and expected-output checks. The runner timestamps also cover the subsequent checksum inventory, so
the two wall times deliberately have different scopes. Slurm accounting can provide an independent
scheduled-job observation. Benchmark aggregation never edits a scientific stage or its manifest.

Reporting follows the same boundary. It reads component authorities but does not alter them. TSV and
FASTA inspection is streaming, while Parquet, DuckDB and SQLite inspection is read-only and bounded.
The stage manifest retains the extracted result summary, so the final report can reuse validated
evidence without reparsing every large result.

The current reuse template supplies native implementations for downloaded domain evidence,
Expression Atlas mapping, computational prioritisation, pocket conservation, integration and app
hand-off. Its reviewed external authorities are immutable checksum-bound inputs. The future fresh
template deliberately retains `CHANGE_ME` component adapter paths until the exact cluster
installation is selected. Controlled inputs are branch-aware, so a reused branch does not require
irrelevant fresh inputs and a disabled branch is not misrepresented in provenance.

## Extension policy

A new species is a new row and FASTA checksum in `proteomes.tsv`, an entry in the orthology species
manifest, and normally a new immutable run name. Species thresholds are fractions so they remain
meaningful as panels grow. Expression and domain resources may be absent for individual species;
their unavailable states and completeness metrics survive into the final resource. New evidence
types should become new tables/views rather than columns injected into unrelated authorities.
DeepClust and OrthoFinder labels are always qualified by their source run identifiers.
