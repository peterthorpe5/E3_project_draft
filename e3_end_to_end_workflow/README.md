# E3 end-to-end workflow

This package is the orchestration layer above the existing E3 project packages. It does not copy
their scientific logic. Snakemake controls dependencies; each component package remains responsible
for its own detailed validation, outputs and scientific interpretation.

Version `0.4.0` upgrades this existing orchestration without replacing any component package. The
shell entry point calls Snakemake, explains what each stage does and why, and exposes safe resume,
start, stop and controlled-rerun options. The dependency graph permits independent Discovery Engine,
OrthoFinder and expression branches to run concurrently. Per-stage threads, memory and runtime
declarations allow Snakemake and Slurm to schedule that concurrency safely. Detailed resource
measurements and run-level benchmark summaries are produced automatically.

The package Conda environment now installs both Snakemake 9 and OrthoFinder 2.5.5. A separately
prepared OrthoFinder environment is neither used nor required for fresh workflow runs.

The complete twelve-stage DAG, manifests, atomic publication, local/Slurm profiles and synthetic
end-to-end test remain in place. The production template still fails closed until the remaining
package adapters are explicitly configured. `CHANGE_ME` values are never treated as defaults.

## DAG and package ownership

| Stage | Owner or planned owner | Publication contract |
|---|---|---|
| `00_inputs` | master workflow | checksummed proteome, seed and shortlist manifests |
| `01_prepared_proteomes` | master adapter | validated species/FASTA inventory |
| `02_discovery` | `e3_discovery_engine` | DIAMOND DeepClust resource |
| `03_candidate_evidence` | `e3_source_to_parquet_seed` | candidate evidence TSV/Parquet/DuckDB |
| `04_orthofinder` | fresh OrthoFinder execution | one isolated, versioned result directory |
| `05_orthology` | `e3_orthology_integration` | parsed identifier and run-specific membership tables |
| `06_domains` | planned domain-evidence component | family/domain evidence, separate from orthology |
| `07_expression` | `expression_downloader` | Expression Atlas Parquet/DuckDB |
| `08_shortlist_gate` | human review plus master validation | approved accession table with sign-off |
| `09_ligandability` | `e3_ligandability_pipeline` | AlphaFold/FPocket/P2Rank resource |
| `10_integrated_resource` | planned release assembler | shared DuckDB plus TSV/Parquet authorities |
| `11_app_ready` | master workflow | Python/Shiny handoff and readiness statement |

DeepClust clusters and OrthoFinder groups remain different concepts. OrthoFinder labels are scoped
to a run. Ligandability is intentionally downstream of a signed shortlist rather than applied to
every cluster member.

## Concurrent execution model

After controlled input preparation, Snakemake can submit the Discovery Engine and fresh OrthoFinder
branches together; expression evidence can also run independently. Candidate evidence waits for
Discovery Engine, and orthology integration waits for OrthoFinder. Domain evidence, orthology and
expression join at the shortlist gate. Snakemake therefore runs every scientifically independent
job it can, up to `--max-jobs` on Slurm or the `--threads` CPU budget locally.

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

1. Copy `config/production.cluster.template.yaml` to a run-specific immutable YAML.
2. Create `proteomes.tsv`, `data/known_e3_seed_evidence.tsv.gz` and the signed shortlist with the
   documented headers.
3. Replace every `CHANGE_ME` argv with a tested adapter command. Commands are YAML argv lists, not
   shell strings; this prevents accidental quoting and injection errors.
4. Set each `expected_outputs` entry to a non-empty file the component publishes only after success.
5. Validate and inspect the DAG before running:

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
and runtime are declared in the YAML, with profile values used only as fallbacks. A production stage
without an explicit command is rejected at configuration load time. Every stage runs under
`.staging`, records file and console logs plus SHA-256 checksums, and is moved to its formal
directory only after its declared output contract passes.

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

## Restart behaviour

Normal Snakemake targets, `--rerun-incomplete`, checksum-bearing stage manifests and persistent stage
control tokens provide the restart boundary. Completed work is reused only when the configured
inputs and outputs remain valid. Completed-job metadata is dropped after success because the
configuration digest, control tokens and checksummed manifests are the workflow's authoritative
restart records; an interrupted job remains marked incomplete.

After a successful wrapper run, transient metadata is explicitly cleared for all completed stage
and benchmark outputs. This cleanup occurs only after Snakemake returns success.

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
