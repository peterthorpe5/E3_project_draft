# Changelog

## 0.1.7 - 2026-07-14

- Expanded every Python function and method docstring using a consistent
  PEP 257-compatible Google style.
- Documented purpose, arguments, return or yield values, and relevant raised
  exceptions, including private helpers and nested generator functions.
- Expanded dataclass documentation with field-level ``Attributes`` sections.
- Added an automated source-documentation contract test covering module, class,
  function and method docstrings.
- Added a code-documentation standard describing the required format for future
  development. No workflow behaviour or scientific logic changed.

## 0.1.6 - 2026-07-14

- Fixed parsing of native DIAMOND 2.2.3 `realign` output, which labels
  representative/member sequence lengths as `clen` and `mlen` rather than
  the requested `qlen` and `slen`.
- Retained support for both query/subject and centroid/member field naming,
  including DIAMOND's capitalised `Bitscore` header.
- Added regression tests using the exact 12-column header observed in the
  external macOS DIAMOND run, a complete Parquet conversion test and the
  Python-managed end-to-end resource build using native DIAMOND field names.
- Corrected README wording so the DeepClust header requirement and tolerant
  historical-file parser are described consistently.

## 0.1.5 - 2026-07-14

- Restored DIAMOND's flag-only `--header` option for `deepclust`. DIAMOND
  2.2.x `realign` requires this native header and rejects a headerless
  clustering-membership file.
- Verified from recovered inherited DeepClust outputs that DIAMOND 2.2.x emits
  the native header `centroid<TAB>member`; the parser accepts this format.
- Added command-construction and parser regression tests for the exact native
  header contract.
- Added a focused diagnostic hint for `Clusters file is missing header line`.

## 0.1.4 - 2026-07-13

- Fixed conversion of real DIAMOND 2.2.3 DeepClust output. Cluster membership
  is now parsed using the documented positional two-column format and no
  longer requires a specific header spelling.
- Added support for recognised header variants including representative/member,
  cseqid/mseqid, centroid/member and cluster-representative labels.
- Made the cluster parser tolerant of both native-header and headerless
  two-column files. Release 0.1.5 restores the native header because DIAMOND
  2.2.x `realign` requires it.
- Applied the configured masking mode consistently to DeepClust and realign.
- Treat a header-only realignment table as a valid zero-row result, which can
  occur when all clusters are singletons, while logging a prominent warning.
- Added unit and integration tests for headerless clustering, header variants,
  comments, malformed rows, empty realignment output and DuckDB construction
  with zero realigned pairs.

## 0.1.3 - 2026-07-13

- Fixed DIAMOND 2.2.3 exact-identity clustering failure: `--id` requires
  alignment traceback, which is incompatible with compositionally adjusted
  matrix modes.
- Added explicit `diamond.comp_based_stats` configuration and pass
  `--comp-based-stats` to both `deepclust` and `realign`.
- Production and end-to-end profiles now use mode `0`; legacy approximate
  reproduction uses mode `1`.
- Added defensive rejection of modes 2-6 for exact identity/realignment.
- Added focused diagnostic hints for the DIAMOND error
  `Traceback with adjusted matrix not supported`.
- Added unit and configuration regression tests for this compatibility rule.

## 0.1.2 - 2026-07-13

- Fixed DIAMOND 2.2.x command construction to use the supported `--db`
  option for `deepclust` and `realign`; `--database` is not accepted by the
  DIAMOND 2.2.3 binary.
- Updated the real-DIAMOND end-to-end test to use `--masking none` rather than
  the unsupported legacy value `0`.
- Added defensive validation for identity mode and masking values.
- Added regression tests that reject `--database` and invalid masking values.

## 0.1.1 - 2026-07-13

- Fixed a macOS-specific unit-test failure caused by `/tmp` resolving to `/private/tmp`.
- Corrected Conda environment files for macOS-64 by removing the invalid
  `channel_priority` key and pinning PyArrow 24.
- Renamed the production Conda environment to `e3_discovery`.
- Added DIAMOND log-tail reporting to external-tool exceptions.
- Added an optional persistent output directory for the external DIAMOND
  end-to-end test to simplify debugging.

## 0.1.0 - 2026-07-13

Initial production rewrite of the inherited Milestone 1 E3 discovery engine.

- Added non-destructive streaming FASTA preparation.
- Added metadata-preserving sequence and seed Parquet tables.
- Added explicit DIAMOND command construction and version checks.
- Added exact realignment outputs and strict post-realignment filters.
- Added E3-seeded cluster DuckDB and curated Parquet resources.
- Added FASTA exports with non-overclaiming names.
- Added benchmark aggregation, plots and provenance manifests.
- Added structured logging, defensive validation and atomic outputs.
- Added unit, integration, synthetic end-to-end and optional external tests.
- Preserved the inherited implementation under `legacy_reference/`.
