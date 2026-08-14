# ARIA E3 Shiny reporter v0.13.0

This release mirrors Python reporter v0.10.0.

## Human and cross-lineage HOG tabs

- Adds **Human HOGs** for every root-level `N0.HOG…` containing
  `Homo_sapiens`.
- Adds **Plant & human HOGs** for the subset also containing at least one of the
  12 curated target plant species.
- Queries remain lazy, read-only and bounded, and load only when explicitly
  requested.
- Summary, human-member and all-member views carry candidate rank/status where
  available, membership metadata, available aliases and candidate-linked
  sequence fields. Each table has TSV and formatted Excel downloads; available
  protein sequences can also be exported as FASTA.

## Complete-resource search

- Adds a dedicated Search tab accepting one item or pasted lists.
- Smart, exact and literal-contains modes search recognised names, HOG/OG IDs,
  E3 seeds, accessions, entries, genes and DeepClust identifiers.
- Search combines unlike relation schemas safely by casting source fields to
  text before row binding, preventing the prior logical/character type clash.
- Summary and complete-hit tables both support TSV and Excel downloads.

## Test additions

- Adds SQL-builder, representative DuckDB, filter-consistency, parsing, schema
  compatibility and UI-contract tests for both feature sets.
