# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.5.1

<!-- source: RELEASE_NOTES_v0_5_1.md; sha256: a4ef11517c4d23e52a7c403f7dfa92892d2eb154c9f655c7cc0141c21fd3e5f2 -->

This corrective release closes the gap between the historical Expression Atlas
download manifest and the strict v0.5 importer contract.

Key changes:

- adds a dedicated preparation command for historical raw downloads;
- resolves legacy relative paths against an explicit raw root;
- computes and records SHA-256 for every retained raw source;
- downloads missing official configuration XML into a separate, versioned
  supplement directory without modifying historical raw files;
- atomically publishes a strict manifest containing absolute paths;
- rejects missing matrices before starting a long expression import;
- requires a matrix and configuration XML for every metadata experiment;
- accepts Atlas's real lexicographic and sparse `gN` matrix identifiers while
  joining every context to configuration XML by literal group ID;
- permits configuration-only groups but rejects every matrix group absent from
  the authoritative XML;
- validates metadata before beginning the much larger expression import;
- adds a fail-fast clean-rebuild wrapper and tests that later stages cannot run
  after a preparation or metadata failure;
- stops immediately with an actionable preflight error instead of reporting
  hundreds of per-file failures and continuing to DuckDB creation;
- corrects the clean-rebuild README sequence and removes a trailing-whitespace
  release warning.

Validation against the final source: 118 Python tests passed at 90%
branch-aware coverage. In addition, the production parser successfully read
all 387 captured real Atlas matrix previews and all 897,650 declared cells;
two freshly retrieved official configuration XML files also mapped exactly by
group identifier for both dense and sparse matrix examples.

## v0.5.0

<!-- source: RELEASE_NOTES_v0_5_0.md; sha256: 1fe244161bb01a49cdb91c18531b2ff6f70a6c15c89da9284f761cc03fc3d911 -->

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
