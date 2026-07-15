# E3 Discovery Engine: Milestone 1 production workflow

Version **0.1.12**

This repository provides a reproducible DIAMOND DeepClust/Snakemake workflow
for:

> **identifying sequence clusters that contain at least one previously
> identified E3 candidate.**

That wording is deliberate. A sequence that belongs to an E3-seeded cluster is
a sequence-similarity candidate; cluster membership alone does **not** establish
that every member is an E3 ligase.

## What the package improves

The inherited workflow demonstrated a useful approach, but it was a research
prototype. This implementation adds:

- non-destructive and atomic file handling;
- stable sample and sequence identifiers;
- preservation of source and biological metadata;
- streaming FASTA and Parquet processing for large datasets;
- explicit DIAMOND version and feature checks;
- automatic whitespace-free path aliases for DIAMOND clustering on macOS
  volumes and other paths containing spaces;
- explicit composition-statistics control so exact identity traceback does not
  use unsupported compositionally adjusted matrices;
- exact realignment fields and an independent strict filtering stage;
- E3-seed detection on the union of representatives and members;
- DuckDB and compressed Parquet interrogation tables;
- representative, complete-member and strict-member FASTA exports;
- explicit all-seed, strict-seed and strict non-seed candidate outputs;
- automatic realignment, key-metric, per-sample, cluster-size and
  cross-species summaries;
- source checksums, Python package versions, Git state and run manifests;
- process-tree peak-RAM and CPU monitoring on macOS and Linux;
- rule-level Snakemake benchmarks and summary figures;
- console and persistent file logging;
- comprehensive PEP 257/Google-style function and method docstrings;
- unit, integration, synthetic end-to-end and optional real-DIAMOND tests;
- retained legacy code for traceability, not execution.

## DIAMOND 2.2 command-line compatibility

The workflow uses DIAMOND's canonical `--db` option for clustering and
realignment. DIAMOND 2.2.x does not accept `--database` as a long option,
even though some documentation describes the input as “database”. Supported
DeepClust performs self-alignment, so the workflow accepts only symmetric
masking modes: `tantan` (recommended), `none`, or no explicit override.
Target-only SEG masking is rejected because DIAMOND 2.2.3 stops with
`asymmetric masking for self alignment`.

DeepClust membership is parsed using DIAMOND's fixed two-column format:
representative accession first, member accession second. The production command
emits DIAMOND's native clustering header because DIAMOND 2.2.x `realign`
requires it. The parser also accepts recognised header variants and headerless
two-column files when importing historical results.

DIAMOND 2.2.3 may relabel requested query/subject realignment fields using
centroid/member names. For example, `qlen`/`slen` can be emitted as
`clen`/`mlen`, and `bitscore` as `Bitscore`. The normalisation layer accepts
both conventions before applying the strict post-realignment filters.

### Paths containing spaces

Snakemake shell commands are quoted, but DIAMOND 2.2.x clustering may still
split database-related paths internally when a workflow root contains
whitespace. The workflow therefore creates a deterministic, whitespace-free
symbolic-link alias under `.e3_path_aliases/` and presents that alias to
`makedb`, `deepclust` and `realign`. Files remain physically stored in the
configured output directory. The mapping is recorded in
`provenance/diamond_path_alias.json`.

An alternative alias parent can be set with `diamond.path_alias_root`. That
path itself must not contain whitespace.

## Scientific interpretation

The workflow creates broad DeepClust groups and then identifies those groups
containing one or more accessions from the supplied known-E3 seed table. A
separate realignment stage records exact percentage identity, representative
coverage, member coverage, bit score and e-value. Strict membership is assigned
only after applying the configured post-realignment thresholds.

The default production thresholds are:

| Criterion | Rule |
|---|---:|
| Percentage identity | >= 50% |
| Representative coverage | >= 50% |
| Member coverage | >= 50% |
| Bit score | > 20 |
| E-value | < 1e-10 |

These thresholds describe sequence similarity to a cluster representative.
They do not replace domain annotation, curated E3 evidence or experimental
validation.

## Repository structure

```text
.
├── Snakefile
├── config/
│   ├── config.yaml                         # small synthetic example
│   ├── config.example.production.yaml      # recommended production template
│   ├── config.example.legacy_reproduction.yaml
│   ├── samples.tsv                         # synthetic example
│   └── samples.production.example.tsv
├── workflow/envs/
├── src/e3_discovery/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── end_to_end/
│   ├── fixtures/
│   └── FUNCTION_TEST_MATRIX.tsv
├── docs/
├── scripts/
└── legacy_reference/
```

## Installation

### Recommended Conda environment

```bash
conda env create -f workflow/envs/production.yml
conda activate e3_discovery
python -m pip install -e .
```

The legacy environment exists only to support controlled reproduction of the
inherited DIAMOND 2.1.23 behaviour:

```bash
conda env create -f workflow/envs/legacy_diamond_2_1_23.yml
```

Do not mix production and legacy results in the same output directory.

## Run the tests first

```bash
./run_tests.sh
```

The test suite includes:

- direct tests for all defined Python functions, tracked in
  `tests/FUNCTION_TEST_MATRIX.tsv`;
- integration tests for DuckDB, Parquet and FASTA exports;
- a synthetic end-to-end test that does not require DIAMOND;
- an optional complete DIAMOND end-to-end test.

Run the external DIAMOND test after creating the production environment:

```bash
E3_DIAMOND_E2E_DIR="${PWD}/test_outputs/diamond_e2e" \
RUN_DIAMOND_E2E=1 python -m unittest \
  tests.end_to_end.test_external_diamond_pipeline -v
```

## Prepare a production configuration

```bash
cp config/config.example.production.yaml config/config.production.yaml
cp config/samples.production.example.tsv config/samples.production.tsv
```

Edit both files. Important points:

1. Each `sample_id` must be unique and contain only letters, digits, `.`, `_`
   or `-`.
2. Every FASTA path must exist.
3. Keep `identifier_mode: prefix_sample` unless sequence identifiers are known
   to be globally unique across all proteomes.
4. Record species, taxon ID, proteome ID, source database, release and access
   restrictions wherever available.
5. Point `e3_seed_table` to the curated known-E3 candidate table and set
   `e3_seed_column` explicitly.
6. Use a new output root for every formal benchmark series.

## Run the complete workflow

The wrapper resolves the configuration path, changes to the repository root and
runs Snakemake with strict failure handling:

```bash
./run_workflow.sh config/config.production.yaml 16
```

Equivalent manual command:

```bash
export E3_DISCOVERY_CONFIG="$(pwd)/config/config.production.yaml"
snakemake \
  --snakefile Snakefile \
  --cores 16 \
  --use-conda \
  --rerun-incomplete \
  --printshellcmds \
  --show-failed-logs
```

Always inspect a dry run first for a new configuration:

```bash
export E3_DISCOVERY_CONFIG="$(pwd)/config/config.production.yaml"
snakemake --snakefile Snakefile --cores 16 --use-conda --dry-run
```

## Main outputs

Under the configured output root:

```text
prepared_inputs/    combined FASTA, sequence metadata and E3 seed tables
diamond/            DIAMOND database, raw clusters and realignments
parquet/            normalised raw cluster and realignment tables
duckdb/             queryable E3 discovery resource
curated_parquet/    one Parquet file per interrogation table
fasta_exports/      representatives, all/strict members, seed and candidate FASTAs
summaries/          key metrics, realignment QC, sample and cluster summaries
resource_metrics/   one process-tree CPU/RAM record per major workflow stage
benchmark_summary/  runtime summaries, resource summaries and RAM figures
qc/                 sample summaries and integrity checks
benchmarks/         rule-level Snakemake benchmark records
benchmark_summary/  consolidated tables and runtime plots
provenance/         commands, checksums, versions and run manifest
logs/               retained stage-specific logs
```

The most useful interrogation tables are:

- `e3_seeded_clusters`
- `e3_seeded_cluster_members`
- `strict_e3_seeded_cluster_members`
- `e3_seeded_cluster_summary`
- `sequence_seed_matches`
- `realigned_membership`
- `workflow_thresholds`

See `docs/DATA_DICTIONARY.md` for field-level definitions.

## Legacy reproduction versus production analysis

The two modes answer different questions:

- **Legacy reproduction** asks whether the inherited result can be recreated
  using DIAMOND 2.1.23 and approximate clustering identity.
- **Production analysis** uses the pinned production environment, exact
  traceback identity during clustering where supported, and strict
  post-realignment thresholds.

A legacy result should never silently overwrite a production result. Use
separate configurations, environments and output roots.

## Benchmarking expectations

Formal Milestone 1 benchmarking should record at least:

- number of proteomes;
- number of sequences;
- total amino-acid residues;
- input FASTA size;
- thread count and memory setting;
- software versions;
- wall-clock and CPU time;
- peak RSS memory;
- input/output I/O;
- output row and cluster counts;
- repeat number;
- hardware and scheduler context.

Run at least three independent repeats for formal comparisons. Do not describe
an extrapolation as a measured runtime. See `docs/BENCHMARK_PROTOCOL.md`.

## Logging and debugging

Each Snakemake rule retains its own log file. External commands also record the
exact argument vector and working directory in JSON. Standalone CLI commands
support persistent logging:

```bash
e3-discovery --verbose --log-file logs/manual_prepare.log \
  prepare --config config/config.production.yaml
```

The original sources are never decompressed in place, modified or deleted.
Incomplete Python-managed outputs are written to temporary files and published
atomically only after successful completion.

## Documentation

- `docs/METHODS.md` - complete computational method
- `docs/SCIENTIFIC_INTERPRETATION.md` - what results do and do not mean
- `docs/DATA_DICTIONARY.md` - DuckDB/Parquet tables and columns
- `docs/BENCHMARK_PROTOCOL.md` - formal benchmark design
- `docs/DATA_SOURCES.md` - source metadata and provenance requirements
- `docs/OPERATIONS_RUNBOOK.md` - routine execution and recovery
- `docs/LEGACY_METHOD_LIMITATIONS.md` - audit of the inherited method
- `docs/RELEASE_CHECKLIST.md` - pre-delivery checks
- `docs/PACKAGE_FILE_REGISTER.md` - role of each principal package file
- `docs/LEGACY_AUDIT_EVIDENCE_REGISTER.md` - inherited evidence used in the audit

## Current validation boundary

The Python unit, integration and synthetic end-to-end suite can run without
DIAMOND. The optional external end-to-end test must be run in the pinned Conda
environment before a formal release or scientific delivery. A full 1KP+ run is
also required before claiming large-scale production performance.

### DIAMOND clustering-header contract

The production DeepClust command includes the flag-only `--header` option.
DIAMOND 2.2.x emits `centroid<TAB>member`, and `diamond realign` requires that
header. The parser remains able to import headerless two-column files for
audit purposes, but a headerless file must not be passed to `realign`.

## Resource monitoring

Every major Snakemake stage is launched with the package's process-tree
monitor. The monitor samples the Python stage process and all descendants,
including DIAMOND, and records aggregate peak resident memory in MiB, wall
time, user and system CPU time, process count and sampling metadata. This is
independent of Snakemake's `max_rss` field, which can be zero on macOS.

The main files are:

```text
resource_metrics/*.tsv
benchmark_summary/resource_usage_records.tsv
benchmark_summary/resource_usage_summary.tsv
benchmark_summary/peak_ram_by_stage.png
benchmark_summary/peak_ram_by_stage.pdf
```

Peak RAM is a sampled process-tree maximum. It is substantially more useful
than a scheduler memory request, but a very short-lived spike between samples
can still be missed. The default sampling interval is 0.2 seconds.

## Explicit seed and candidate outputs

The resource keeps all inherited E3 seed matches even when a seed does not
pass the strict alignment thresholds against its DeepClust representative. It
also separates the candidate expansion from the inherited evidence:

```text
all_matched_e3_seed_sequences
strict_matched_e3_seed_sequences
non_strict_matched_e3_seed_sequences
strict_nonseed_candidate_members
```

`strict_nonseed_candidate_members` contains proteins absent from the supplied
seed list that pass every configured representative-alignment threshold inside
an E3-seeded cluster. These are sequence-similarity candidates, not confirmed
E3 ligases.

## University of Dundee Slurm full 1KP+ run

Version 0.1.13 adds a cluster-specific full-run route while retaining the
existing local configurations and macOS driver scripts. The Slurm route uses:

```text
account:   barton
partition: general
```

The default cluster source root is:

```text
/home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data
```

The 1KP scaffold identifiers are parsed per sequence. For example,
`scaffold-AALA-2000001-Meliosma_cuneifolia` is recorded as 1KP sample `AALA`
and species `Meliosma cuneifolia`; the source FASTA remains
`onekp_dataset.fasta`.

Submit from the cluster repository checkout:

```bash
./scripts/submit_full_onekp_slurm.sh
```

Check progress:

```bash
./scripts/check_full_onekp_slurm.sh --job-id <JOB_ID>
```

The submission defaults to 32 CPUs, 256 GiB Slurm memory, a 220 GiB DIAMOND
limit and seven days. It also requires at least 150 GiB free in persistent
results storage and 100 GiB free in the selected job-scratch filesystem before
expensive work starts. All values can be overridden on the command line. Large
persistent results are kept below
`/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results`; job-local
scratch is used for DIAMOND temporary files. See
`docs/SLURM_FULL_ONEKP_RUNBOOK.md` for the complete procedure and restart
behaviour.
