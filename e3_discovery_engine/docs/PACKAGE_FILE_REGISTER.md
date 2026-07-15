# Package file register

This register explains the role of the principal files in release 0.1.13.
Generated run outputs are deliberately excluded from the source package.

## Workflow and configuration

| Path | Purpose |
|---|---|
| `Snakefile` | End-to-end Snakemake orchestration, logs, benchmarks and non-empty output contracts. |
| `config/config.example.production.yaml` | Production template using exact clustering identity and strict post-realignment filtering. |
| `config/config.example.legacy_reproduction.yaml` | Controlled approximation of the inherited DIAMOND 2.1.23 behaviour. |
| `config/config.yaml` | Tiny synthetic example suitable for development. |
| `config/samples.production.example.tsv` | Metadata-rich production sample-manifest template. |
| `config/samples.tsv` | Synthetic test/example sample manifest. |
| `workflow/envs/production.yml` | Pinned Conda environment for production analysis. |
| `workflow/envs/legacy_diamond_2_1_23.yml` | Separate environment for legacy reproduction only. |

## Python package

| Module | Responsibility |
|---|---|
| `benchmarks.py` | Parse, aggregate, summarise and plot Snakemake benchmark records. |
| `cli.py` | Command-line interface and stage routing. |
| `clusters.py` | Headerless/header-tolerant cluster parsing, realignment parsing, exact coverage calculations and strict threshold classification. |
| `config.py` | YAML loading, path resolution and defensive configuration validation. |
| `constants.py` | Stable package constants. |
| `diamond.py` | DIAMOND version checks, argument-array construction, execution and output validation. |
| `exceptions.py` | Package-specific exception hierarchy. |
| `fasta.py` | Streaming FASTA parsing, validation, stable identifiers and sequence Parquet writing. |
| `io_utils.py` | Atomic file operations, checksums and delimited-file helpers. |
| `logging_utils.py` | Console and persistent file logging configuration. |
| `manifest.py` | Proteome sample-manifest reading, validation and normalised writing. |
| `pipeline.py` | Configuration-driven orchestration of Python-managed stages. |
| `path_safety.py` | Whitespace-safe external-tool path aliases and provenance records for DIAMOND. |
| `provenance.py` | External and Python package versions, Git state, file manifests and run provenance JSON. |
| `resource.py` | DuckDB/Parquet construction, validation, scientific summaries and candidate/seed FASTA exports. |
| `resource_monitor.py` | Cross-platform process-tree CPU and peak-RAM monitoring, aggregation and figures. |
| `seeds.py` | Known-E3 seed normalisation, deduplication and metadata preservation. |

## Tests

| Path | Purpose |
|---|---|
| `tests/unit/` | Function-level behaviour, edge cases and repository/workflow contracts. |
| `tests/integration/` | Real DuckDB/Parquet integration and query checks. |
| `tests/end_to_end/test_end_to_end_synthetic.py` | Complete Python-managed workflow without DIAMOND. |
| `tests/end_to_end/test_external_diamond_pipeline.py` | Opt-in complete run using a real DIAMOND executable. |
| `tests/FUNCTION_TEST_MATRIX.tsv` | Machine-checked map from every source function to test files. |
| `tests/fixtures/` | Small deterministic sequences, seeds, clusters and realignments. |

## Documentation

| Path | Purpose |
|---|---|
| `README.md` | Installation, execution, outputs and interpretation overview. |
| `docs/METHODS.md` | Detailed computational method. |
| `docs/SCIENTIFIC_INTERPRETATION.md` | Permitted claims and evidence levels. |
| `docs/DATA_DICTIONARY.md` | Field-level resource schema. |
| `docs/BENCHMARK_PROTOCOL.md` | Formal repeat/scaling benchmark design. |
| `docs/DATA_SOURCES.md` | Input metadata and provenance requirements. |
| `docs/OPERATIONS_RUNBOOK.md` | Routine execution and failure recovery. |
| `docs/LEGACY_METHOD_LIMITATIONS.md` | Technical/methodological audit of inherited workflow. |
| `docs/LEGACY_AUDIT_EVIDENCE_REGISTER.md` | Inherited files and evidence used in the audit. |
| `docs/EXAMPLE_QUERIES.sql` | Example DuckDB interrogation queries. |
| `docs/TESTING.md` | Test layers and validation boundary. |
| `docs/RELEASE_CHECKLIST.md` | Pre-delivery quality gate. |
| `docs/CODE_DOCUMENTATION_STANDARD.md` | Required PEP 257/Google-style docstring structure and automated checks. |
| `docs/RESOURCE_MONITORING.md` | Meaning, implementation and limits of process-tree CPU and RAM measurements. |

## Legacy reference

Files below `legacy_reference/` are preserved unchanged or as recovered for
traceability. They are not imported by the production package and must not be
used as the execution path for formal results.


## Version 0.1.13 cluster additions

| Path | Purpose |
|---|---|
| `src/e3_discovery/sequence_metadata.py` | Parse biological sample and species metadata from inherited 1KP scaffold identifiers. |
| `src/e3_discovery/cluster_config.py` | Generate the full 1KP+ cluster manifest and executable YAML configuration. |
| `config/config.cluster.full_onekp.example.yaml` | Readable example of the generated Slurm configuration. |
| `config/full_onekp_cluster.example.samples.tsv` | Readable example of the 15-source full-run manifest. |
| `scripts/submit_full_onekp_slurm.sh` | Submit the production job with explicit Dundee account, partition and resources. |
| `scripts/slurm_full_onekp_job.sh` | Generate inputs, run Snakemake, validate outputs and create the review bundle on a compute node. |
| `scripts/check_full_onekp_slurm.sh` | Display queue, accounting, logs, completion markers and review-bundle path. |
| `docs/SLURM_FULL_ONEKP_RUNBOOK.md` | Detailed cluster paths, submission, monitoring, restart and interpretation instructions. |
| `scripts/run_e3_scaling_and_full.sh` | Retained local scaling/full driver, now using per-sequence 1KP metadata when full mode is selected. |
| `scripts/run_five_proteome_masking_comparison.sh` | Retained local paired masking-comparison driver. |
