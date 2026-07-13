# Package file register

This register explains the role of the principal files in release 0.1.0.
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
| `clusters.py` | Cluster/realignment parsing, exact coverage calculations and strict threshold classification. |
| `config.py` | YAML loading, path resolution and defensive configuration validation. |
| `constants.py` | Stable package constants. |
| `diamond.py` | DIAMOND version checks, argument-array construction, execution and output validation. |
| `exceptions.py` | Package-specific exception hierarchy. |
| `fasta.py` | Streaming FASTA parsing, validation, stable identifiers and sequence Parquet writing. |
| `io_utils.py` | Atomic file operations, checksums and delimited-file helpers. |
| `logging_utils.py` | Console and persistent file logging configuration. |
| `manifest.py` | Proteome sample-manifest reading, validation and normalised writing. |
| `pipeline.py` | Configuration-driven orchestration of Python-managed stages. |
| `provenance.py` | Software versions, file manifests and run provenance JSON. |
| `resource.py` | DuckDB/Parquet construction, validation and candidate FASTA exports. |
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

## Legacy reference

Files below `legacy_reference/` are preserved unchanged or as recovered for
traceability. They are not imported by the production package and must not be
used as the execution path for formal results.
