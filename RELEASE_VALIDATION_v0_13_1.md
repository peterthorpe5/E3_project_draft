# Repository corrective source update v0.13.1

Date: 2026-08-04

## Scope

This is a corrective repository-source update for the Expression Atlas clean
rebuild. Workflow v0.13.0 and the non-expression scientific packages are not
version-bumped by this update.

## Defects corrected

- The historical downloaded-files manifest used working-directory-relative
  paths that did not resolve from the documented cluster command location.
- The historical manifest had no SHA-256 column and no configuration-XML rows.
- Metadata import did not preflight its required expression matrix and XML.
- Tests incorrectly assumed numerically ordered, contiguous `g1..gN` columns.
  Real Atlas matrices may be lexicographically ordered and use sparse group
  identifiers.
- Individually pasted import commands could continue to DuckDB creation after
  an earlier non-zero import result.

## Corrected contract

- Historical raw downloads and their manifest remain unchanged.
- A dedicated preparation step resolves files beneath an explicit raw root,
  verifies or calculates checksums, acquires missing official configuration
  XML into a new supplement directory, and atomically publishes an absolute-
  path strict manifest.
- Every matrix group is a unique valid `gN` identifier and must occur in the
  official XML. Order and gaps are accepted as source properties; XML-only
  groups are permitted. Mapping is by literal identifier, never position.
- Metadata validates before the larger matrix import.
- The clean-rebuild wrapper stops at the first failure and prevents DuckDB
  publication from incomplete Parquet inputs.

## Executed validation

- Expression package: 118 Python tests passed, zero failed.
- Expression branch-aware coverage: 90%, meeting the enforced gate.
- Repository contracts: 15 tests passed, zero failed.
- Real snapshot: 387 matrix previews and 897,650 declared cells parsed without
  structural rejection or silent loss.
- Official XML checks: E-CURD-1 mapped 57/57 matrix groups; E-MTAB-4723 mapped
  all five sparse matrix groups.
- Real mini rebuild: a legacy E-CURD-1 manifest completed through preparation,
  real condensed SDRF, official XML, Parquet and DuckDB. The result contained
  50 genes, 57 groups and 2,850 joined rows; every row had tissue context and a
  configuration checksum, with zero expression/metadata checksum mismatches.
- `git diff --check`, Python compilation, pycodestyle, Google-style pydocstyle,
  Ruff and shell syntax checks passed through the package gate.

R is unavailable in the release container. The package's R query-helper suite
must still run in the cluster R environment before the full rebuilt resource is
accepted.

## Operator entry point

Use `expression_downloader/inst/scripts/run_clean_rebuild_from_existing.sh`
with the absolute historical manifest, raw root and a new v0.5.1 output root.
The exact project paths and validation queries are in
`expression_downloader/README.md`.
