# Testing strategy

## Test layers

### Unit tests

Every Python function or class method defined under `src/e3_discovery` is mapped
to one or more test files in `tests/FUNCTION_TEST_MATRIX.tsv`. A contract test
parses the source abstract syntax tree and fails if a function is not mapped.
Tests include normal behaviour, invalid inputs, empty files, duplicate IDs,
sidecar files, atomic-write cleanup and external-command failures.

### Integration tests

Integration tests construct real Parquet inputs, build a DuckDB resource, query
curated tables, validate counts and inspect FASTA exports.

### Synthetic end-to-end test

A complete Python-managed workflow is executed from sample/seed preparation
through cluster conversion, strict filtering, DuckDB construction and
provenance. This test requires no DIAMOND executable and therefore runs in all
CI/development environments.

### External DIAMOND end-to-end test

An opt-in test creates a tiny DIAMOND database, runs DeepClust and realignment,
then builds the final resource. It is skipped unless `RUN_DIAMOND_E2E=1` and a
compatible `diamond` executable is available.

## Commands

```bash
./run_tests.sh
```

The script performs compilation, PEP8 checking, unit/integration/end-to-end
execution and coverage reporting.

```bash
RUN_DIAMOND_E2E=1 python -m unittest \
  tests.end_to_end.test_external_diamond_pipeline -v
```

## Validation boundary

Passing the Python suite proves the data handling and resource logic against
controlled fixtures. It does not replace a full production run with the pinned
DIAMOND/Snakemake environment and intended input dataset.
