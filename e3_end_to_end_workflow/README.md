# E3 end-to-end workflow

This package is the orchestration and evidence-integration layer above the existing E3 project
packages. Snakemake controls dependencies; each component package remains responsible for its
detailed scientific analysis, while the master package enforces shared manifests, missing-data
semantics, scoring, provenance, reporting and application hand-off.

Version `0.6.0` supports two equally explicit production strategies:

- **reviewed reuse** for the current grant analysis: reuse checksum-bound Discovery/candidate,
  OrthoFinder 2.5.5, Expression Atlas and ligandability results, then rebuild every join, ranking,
  conserved-pocket comparison, report and application resource; and
- **fresh scalable execution** for a future, larger proteome panel: prepare an arbitrary manifest
  of proteomes and run configured component adapters under the same output contracts.

Every enabled stage declares an `evidence_mode` (`validate`, `prepare`, `reuse`, `download`,
`derive` or `generate`). Reports and manifests therefore distinguish reused evidence from newly
computed evidence. Per-stage threads, memory and runtime are configuration values rather than fixed
species-count assumptions. Detailed resource measurements, stage HTML reports and the consolidated
full-run HTML report are produced automatically.

The package Conda environment now installs both Snakemake 9 and OrthoFinder 2.5.5. A separately
prepared OrthoFinder environment is neither used nor required for fresh workflow runs.

The complete twelve-stage DAG, manifests, atomic publication, local/Slurm profiles and synthetic
end-to-end test remain in place. The reusable current-study template contains the reviewed paths
already known to the project and fails closed only for the ligandability resource manifest that
must be built from the retained result roots. The future fresh template uses explicit
`CHANGE_ME` adapter paths and never treats a placeholder as a default.

## DAG and package ownership

| Stage | Owner | Publication contract |
|---|---|---|
| `00_inputs` | master workflow | branch-aware, checksummed controlled-input inventory |
| `01_prepared_proteomes` | native master adapter | validated, isolated species/FASTA inventory |
| `02_discovery` | `e3_discovery_engine` | reused authority or fresh DIAMOND/DeepClust resource |
| `03_candidate_evidence` | `e3_source_to_parquet_seed` | reused or fresh candidate evidence authority |
| `04_orthofinder` | OrthoFinder 2.5.5 | reviewed archive reuse or fresh isolated result |
| `05_orthology` | `e3_orthology_integration` | parsed identifier and run-specific membership tables |
| `06_domains` | native download/cache adapter | InterPro/Pfam hits and tri-state domain evidence |
| `07_expression` | native Expression Atlas adapter | full selected-group mapping and expression summary |
| `08_shortlist_gate` | native prioritisation | scored candidates, structural accessions and review template |
| `09_ligandability` | native reuse/conservation adapter | best pockets and aligned pocket-region conservation |
| `10_integrated_resource` | native release assembler | DuckDB, final TSV/Parquet and scientific HTML |
| `11_app_ready` | native hand-off | Python/Shiny configuration and release manifest |

DeepClust clusters and OrthoFinder groups remain different concepts. OrthoFinder labels are scoped
to a run. The computational shortlist controls expensive structural analysis; it is a transparent
recommendation for human review, not a pre-existing signed approval falsely represented as evidence.

## Missing evidence policy

Missing coverage is allowed and is never silently converted to a biological failure.

- Domain evidence is `SUPPORTED`, `ANNOTATED_NO_CATALOGUED_E3_DOMAIN`, or
  `ANNOTATION_UNAVAILABLE`. Only the second state is a true annotated negative.
- Expression evidence distinguishes mapped support, limited/zero measurements, mapping failure and
  unavailable species resources.
- Structural evidence distinguishes a completed prediction below threshold from a protein with no
  available model or pocket result.
- Fractions use only species for which the relevant evidence could actually be assessed; separate
  completeness fields expose the missing denominator.

Stage 06 does not require a local InterProScan or Pfam HMM installation. It retrieves bounded
InterPro/Pfam annotation JSON for the accessions in the selected orthology groups, caches every
terminal response and can later run entirely from a checksum manifest. This makes the current reuse
analysis economical and lets a larger future run populate the same shared cache incrementally.

## Concurrent execution model

After controlled input preparation, Snakemake can submit fresh Discovery Engine and OrthoFinder
branches together. Candidate evidence waits for Discovery; orthology integration waits for both
candidate evidence and OrthoFinder. Domain and expression mapping then interrogate the complete
members of the selected run-specific groups before joining at prioritisation. Reuse stages can
replace either fresh branch without changing the downstream contracts.

This is concurrency between stages. Each component package remains responsible for safe
multithreading within its own stage.

## Install and prove the installation

```bash
cd e3_end_to_end_workflow
conda env create --file environment.yml
conda activate e3_end_to_end_workflow
python -m pip install --no-deps --editable .
./run_tests.sh
./run_e3_end_to_end.sh --dry-run
```

The environment pins OrthoFinder exactly because its output contract is part of the scientific
provenance. Recreate the environment from `environment.yml`; do not borrow `orthofinder` from a
different activated environment.

## OrthoFinder version policy

The OrthoFinder version is fixed across the inherited reference and new workflow runs:

- The inherited `Results_Feb26` result remains a frozen OrthoFinder 2.5.5 reference. It is never
  overwritten or extended.
- New isolated end-to-end runs use exactly OrthoFinder 2.5.5 from this package environment. This
  matches the boss-approved version, preserves the project-reviewed phylogeny that was preferred
  over the version-3 result, and follows the input contract already validated by
  `e3_orthology_integration`. This is a dataset-specific project decision rather than a claim that
  version 2 is universally more accurate than version 3.

Stage 04 requires both `Orthogroups/Orthogroups.tsv` and the version-2 root hierarchical grouping at
`Phylogenetic_Hierarchical_Orthogroups/N0.tsv`. Run-specific identifiers must not be merged with
identifiers from `Results_Feb26` merely because their labels look similar. Adding species creates a
new, separately versioned complete-proteome analysis rather than modifying the inherited result.

The committed synthetic configuration uses two tiny, visibly synthetic FASTAs and runs all stages.
Its outputs contain `TEST DATA ONLY` and are never production eligible.

## Production preparation

For the current reviewed-results analysis, copy
`config/grant_aligned_reuse.cluster.template.yaml` to an immutable run-specific YAML. Build the
Expression Atlas and ligandability manifests with the supplied CLI commands, keep the existing
OrthoFinder archive read-only, and validate the configuration. For a larger future analysis, copy
`config/production.cluster.template.yaml`, add any number of proteome rows/species and configure the
fresh component adapter argument vectors. Commands are YAML argv lists rather than shell strings.

Both modes use the same validation and submission interface:

```bash
e3-workflow validate --config /path/to/run.yaml
e3-workflow plan --config /path/to/run.yaml
./run_e3_end_to_end.sh --config /path/to/run.yaml --profile slurm --dry-run
./run_e3_end_to_end.sh \
    --config /path/to/run.yaml \
    --profile slurm \
    --max-jobs 50 \
    --resume
```

The Slurm profile defaults to account `barton`, partition `general`. Stage-specific threads, memory
and runtime are declared in the YAML, with profile values used only as fallbacks. The fresh template
permits up to 32 threads and 180 GB for expensive components, while the current reuse stages request
substantially less. A production stage without an explicit command or a documented native
implementation is rejected at configuration load time. Every stage runs under
`.staging`, records file and console logs plus SHA-256 checksums, and is moved to its formal
directory only after its declared output contract passes.

`config/five_proteome_orthofinder.cluster.yaml` remains a bounded fresh-OrthoFinder demonstration.
It is not the current grant analysis and does not supersede the reviewed 60-proteome
`Results_Feb26` authority.

See [docs/EVIDENCE_MODES_AND_SCALING.md](docs/EVIDENCE_MODES_AND_SCALING.md) for the evidence-state,
reuse and larger-panel contracts.

## Benchmarking and resource provenance

Benchmarking is automatic for every full run; no separate profiling command is required. Multiple
scopes are retained:

- the stage monitor samples the stage process tree while its scientific command and output
  validation run;
- runner timestamps cover the broader stage orchestration through checksum inventory; and
- Slurm accounting, when available, independently describes the complete scheduled job.

Each stage publishes `benchmark/stage_resource_usage.tsv`, a matching JSON record and a compressed
`stage_resource_timeseries.tsv.gz`. The final aggregation rule writes run-wide outputs under
`benchmark_summary/`, including a 12-row stage comparison, whole-workflow metrics and optional raw
Slurm accounting records. CPU time, wall time, allocation efficiency, peak RSS/VMS, process and
thread counts, I/O counters, context switches, requested resources, output sizes and execution
context are retained where the operating system exposes them.

Set the sampling and accounting policy in the run YAML:

```yaml
benchmarking:
  sample_interval_seconds: 5.0
  collect_slurm_accounting: true
```

Measurements from a failed stage are retained under `failed/`. Slurm accounting is best-effort:
an unavailable or delayed `sacct` service is recorded in `slurm_accounting_status.tsv` but does not
invalidate successful process-tree measurements. See [docs/BENCHMARKING.md](docs/BENCHMARKING.md)
for field definitions and interpretation limits.

## Verbose HTML reports

Every successfully published stage contains:

```text
<run_root>/<stage>/report/stage_report.html
```

The report is generated after declared outputs validate and before atomic stage publication. It is
then included in the stage manifest's checksum inventory. Each stage report contains:

- what the stage did, why it was needed, the supported interpretation and an explicit scientific
  limitation;
- direct input paths, byte sizes and SHA-256 checksums;
- the exact external argument vector, or the named internal implementation;
- start/finish state, declared output validation and links to stage/tool logs;
- measured wall time, CPU, peak RSS/VMS, I/O, processes, threads, scheduler context and embedded
  CPU/RAM time-series graphics;
- declared-output sizes, checksums and evidence-based summaries; and
- bounded result previews for TSV/TSV.GZ, FASTA, Parquet, DuckDB, SQLite, JSON and text outputs.

Large data authorities are never embedded into HTML. TSV and FASTA files are inspected by streaming;
Parquet and database files are queried read-only. Preview rows and columns are bounded by the YAML:

```yaml
reporting:
  preview_rows: 10
  max_table_columns: 12
  max_chart_items: 20
```

After all twelve stages and the benchmark aggregate complete, Snakemake publishes:

```text
<run_root>/reports/e3_workflow_summary.html
<run_root>/reports/report_manifest.json
<run_root>/reports/report_complete.tsv
```

The consolidated report includes the controlled inputs, full shell-to-Snakemake invocation history,
per-stage commands and summaries, workflow metrics, inline stage-comparison graphics and links to
every detailed stage report. It is self-contained HTML5 with embedded CSS/SVG and therefore remains
readable when copied away from the cluster, although links to the original result files naturally
require the run directory to remain together. A partial `--stop-after` run has reports for every
completed stage but does not claim a complete-run report.

See [docs/REPORTING.md](docs/REPORTING.md) for the complete reporting contract and interpretation
rules.

## Restart behaviour

Normal Snakemake targets, `--rerun-incomplete`, checksum-bearing stage manifests and persistent stage
control tokens provide the restart boundary. Completed work is reused only when the configured
inputs and outputs remain valid. Completed-job metadata is dropped after success because the
configuration digest, control tokens and checksummed manifests are the workflow's authoritative
restart records; an interrupted job remains marked incomplete.

The profiles set `drop-metadata: true`, so Snakemake does not retain completed-job metadata after
successful jobs. After the complete default target succeeds, the wrapper also clears incomplete
markers for every declared, successfully published output. This narrow compatibility step addresses
a Snakemake 9 multi-output timing edge case; it runs only after the full DAG succeeds and tolerates
the expected "metadata was not present" return because completed metadata has already been dropped.
It never runs after a partial target or a failed/interrupted DAG. Checksummed manifests and control
tokens remain the restart authority.

Use named controls rather than deleting outputs:

```bash
./run_e3_end_to_end.sh --config /path/to/run.yaml --profile slurm --resume
./run_e3_end_to_end.sh --config /path/to/run.yaml --profile slurm \
    --start-at 04_orthofinder --stop-after 05_orthology
./run_e3_end_to_end.sh --config /path/to/run.yaml --profile slurm \
    --force-stage 07_expression
```

`--start-at` refreshes the selected stage control token and propagates the rerun through the DAG. It
does not bypass missing or invalid prerequisites. Existing stage directories are moved under
`superseded` when a rerun is published. Failed staging directories are retained under `failed`.

## Known-E3 evidence resource

The production seed evidence is a deterministic derivative of the discovery engine's authoritative
`prepared_inputs/known_e3_seeds.tsv`. It retains the accession, E3 category, GO evidence flags,
organism, taxon, sequence MD5 and source-row provenance without storing the full sequence-bearing
51 MB table in Git.

Build it on the cluster from the workflow package root:

```bash
e3-workflow build-seed-evidence \
    --source /home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results/full_onekp_plus_v0_1_14_20260715_100551/prepared_inputs/known_e3_seeds.tsv \
    --output data/known_e3_seed_evidence.tsv.gz
```

The command also writes `data/known_e3_seed_evidence.provenance.tsv`. Existing outputs are protected;
use `--force` only when intentionally rebuilding them from a reviewed source.

The seed archives and provenance sidecars committed in `data/` are controlled inputs. Workflow
upgrades must preserve them byte-for-byte; a run stages and checksums them but never rewrites them.
