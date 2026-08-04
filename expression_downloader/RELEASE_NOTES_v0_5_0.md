# E3AtlasDuckplyr v0.5.0

This release replaces the former expression parser contract with a verified,
fail-closed Expression Atlas pipeline.

Key changes:

- interprets Atlas five-number summaries as minimum, lower quartile, median,
  upper quartile and maximum, publishing the median;
- retains all five statistics and distinguishes measured zero from unavailable
  evidence;
- rejects malformed, non-finite, negative, unordered, truncated, duplicated
  and ambiguous matrix data;
- maps `g1..gN` conditions through authoritative configuration XML assay groups;
- retains tissue, stage, treatment, condition, experiment and assay context;
- checksum-binds expression, metadata and XML inputs through Parquet and joins;
- selects TPM per experiment and uses FPKM only as a recorded fallback;
- validates uniqueness and join cardinality before atomically publishing DuckDB;
- retires the old R parser and old R-manifest download route;
- adds a raw-matrix-to-DuckDB known-answer test and a 90% coverage release gate.

Validation in the release environment: 99 Python tests passed at 91%
branch-aware coverage. R `testthat` remains required in an R-enabled release
environment.
