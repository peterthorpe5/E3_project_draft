# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.1.1

<!-- source: RELEASE_NOTES_v0_1_1.md; sha256: 6a9b8564000524fb9548b2eadd6c6455b90d52041e0da9daa9f7b20fbf6df5f4 -->

### Reason for release

The first real Q9SA03 FPocket/P2Rank smoke test completed the external tools
but failed during parsing of `pocket1_atm.cif`. The v0.1.0 parser incorrectly
reused the strict AlphaFold model parser, which required a full set of
`_atom_site` columns including `B_iso_or_equiv`. FPocket derivative pocket
mmCIF files may legitimately omit those model-only columns.

### Changes

- Added a dedicated reduced-FPocket mmCIF parser.
- Requires a residue name and at least one usable label or author residue ID.
- Treats label and author chain columns as optional and cross-fills only chain
  identifiers, never residue numbers.
- Excludes hetero atoms from the protein pocket-residue list.
- Preserves the strict AlphaFold model parser and pLDDT calculation unchanged.
- Added sparse FPocket 4.2.2-style mmCIF fixtures and defensive malformed-file
  tests.
- Updated test traceability for every production function.
- Updated the AlphaFold request user agent to v0.1.1.

### Scientific effect

No Q9SA03 pocket result was produced by v0.1.0. The workflow failed safely
before publishing FPocket, P2Rank, joined-pocket or pocket-quality tables.
Version 0.1.1 repairs output parsing; it does not alter the already validated
model-level pLDDT results. The Q9SA03 smoke test must be rerun and its pocket
mapping and inherited-result agreement reviewed before pocket-level methods
are considered validated.

## v0.1.0

<!-- source: RELEASE_NOTES_v0_1_0.md; sha256: a09b841d6f4640225f007fd92f6d03c34fcbc38ecb5a52b3b19e43a8574e1d1e -->

Initial production release of the ARIA plant E3 ligandability workflow.

### Added

- safe AlphaFold metadata selection and asset materialisation;
- direct model-derived pLDDT calculation;
- explicit model/API quality comparison;
- FPocket plus P2Rank rescoring command orchestration;
- atomic external-tool output publication;
- FPocket/P2Rank parsers;
- label/author residue-number mapping with ambiguity detection;
- conservative pocket-confidence calculations;
- TSV, Parquet and materialised DuckDB outputs;
- QC and full run provenance;
- pinned FPocket 4.2.2 from the recovered inherited environment;
- required P2Rank 2.5.1 preflight for inherited comparability;
- local/Conda and Slurm shell wrappers;
- inherited model-level regression command;
- frozen legacy scripts and checksums;
- comprehensive unit, integration, command-line and release-contract tests.

### Scientific release state

The software release is tested with synthetic fixtures and fake external
executables. Real FPocket/P2Rank cluster validation remains deliberately
pending. The next action is controlled regression against the inherited test
set followed by a one- or two-model smoke run. No full inherited collection
rerun is recommended.
