# e3_structural_alignment v0.2.0

Version 0.2.0 adds a top-k member-pocket sensitivity analysis while preserving
the original selected-pocket comparison as the primary stringent result.

For each reference-to-member structural pair, each enabled aligner is executed
once. The resulting whole-structure transform is then applied to every retained
member-pocket candidate. A member is supported only when all enabled aligners
assess and support the same pocket number. Lower-ranked rescues, strict and
sensitivity support fractions, and residue-level evidence are published in
separate TSV and Parquet relations.

New command-line options:

- `--ranked-pockets`
- `--ranked-pocket-sequence-coordinates`
- `--member-pocket-top-k`

The top-k limit is validated between one and twenty. Rank-one inputs remain
backward-compatible.
