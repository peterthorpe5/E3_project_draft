# E3 Discovery Engine: Milestone 1 production workflow

Version **0.1.8**

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
- explicit composition-statistics control so exact identity traceback does not
  use unsupported compositionally adjusted matrices;
- exact realignment fields and an independent strict filtering stage;
- E3-seed detection on the union of representatives and members;
- DuckDB and compressed Parquet interrogation tables;
- representative, complete-member and strict-member FASTA exports;
- source checksums, software versions and run manifests;
- rule-level Snakemake benchmarks and summary figures;
- console and persistent file logging;
- comprehensive PEP 257/Google-style function and method docstrings;
- unit, integration, synthetic end-to-end and optional real-DIAMOND tests;
- retained legacy code for traceability, not execution.

## DIAMOND 2.2 command-line compatibility

The workflow uses DIAMOND's canonical `--db` option for clustering and
realignment. DIAMOND 2.2.x does not accept `--database` as a long option,
even though some documentation describes the input as “database”. Supported
masking values are validated before execution: `none`, `seg`, `seg-all` and
`tantan`.

DeepClust membership is parsed using DIAMOND's fixed two-column format:
representative accession first, member accession second. The production command
emits DIAMOND's native clustering header because DIAMOND 2.2.x `realign`
requires it. The parser also accepts recognised header variants and headerless
two-column files when importing historical results.

DIAMOND 2.2.3 may relabel requested query/subject realignment fields using
centroid/member names. For example, `qlen`/`slen` can be emitted as
`clen`/`mlen`, and `bitscore` as `Bitscore`. The normalisation layer accepts
both conventions before applying the strict post-realignment filters.

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
fasta_exports/      representative, all-member and strict-member FASTAs
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
