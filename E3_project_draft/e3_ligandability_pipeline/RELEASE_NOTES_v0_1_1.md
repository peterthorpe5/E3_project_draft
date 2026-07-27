# Release notes: v0.1.1

## Reason for release

The first real Q9SA03 FPocket/P2Rank smoke test completed the external tools
but failed during parsing of `pocket1_atm.cif`. The v0.1.0 parser incorrectly
reused the strict AlphaFold model parser, which required a full set of
`_atom_site` columns including `B_iso_or_equiv`. FPocket derivative pocket
mmCIF files may legitimately omit those model-only columns.

## Changes

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

## Scientific effect

No Q9SA03 pocket result was produced by v0.1.0. The workflow failed safely
before publishing FPocket, P2Rank, joined-pocket or pocket-quality tables.
Version 0.1.1 repairs output parsing; it does not alter the already validated
model-level pLDDT results. The Q9SA03 smoke test must be rerun and its pocket
mapping and inherited-result agreement reviewed before pocket-level methods
are considered validated.
