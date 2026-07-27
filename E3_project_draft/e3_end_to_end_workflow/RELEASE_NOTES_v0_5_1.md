# E3 end-to-end workflow v0.5.1

This production-readiness release enables the first bounded, real five-proteome OrthoFinder run.
It does not change the selected OrthoFinder version or downstream scientific logic.

## Production preparation

- Added a native production implementation for `01_prepared_proteomes`.
- Requires filename-safe, unique species identifiers.
- Validates FASTA structure, non-empty records and unique primary sequence identifiers.
- Copies every selected FASTA into the run's isolated OrthoFinder input directory.
- Verifies copied files against the controlled source SHA-256 values.
- Publishes sequence, residue, byte and checksum statistics in `prepared_proteomes.tsv` and HTML.

## Bounded branches

- Controlled-input validation is now branch-aware.
- Proteomes remain mandatory for every run.
- Known-E3 seed evidence is required when Discovery is enabled.
- A signed shortlist is required only when the human-review gate is enabled.
- An OrthoFinder-only production run therefore cannot be forced to invent a future shortlist.
- Added the immutable `five_proteome_orthofinder_v0_1_0_20260722` cluster configuration.
- Consolidated reports distinguish a complete bounded run from a complete application release and
  list every explicitly skipped stage.
- Successful full runs retry Snakemake incomplete-marker cleanup across bounded filesystem latency.

## Verification

- 83 tests pass.
- Branch-aware coverage remains 95%.
- PEP 8, PEP 257, Python compilation and shell syntax pass.
- OrthoFinder remains pinned exactly at 2.5.5.
- The controlled GitHub `data/` resources are not modified or bundled.
