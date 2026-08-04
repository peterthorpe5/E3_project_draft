# E3AtlasDuckplyr v0.5.1

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
