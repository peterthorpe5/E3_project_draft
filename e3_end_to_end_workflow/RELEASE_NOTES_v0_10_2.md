# e3_end_to_end_workflow v0.10.2

Release date: 28 July 2026

Version 0.10.2 repairs three defects exposed by the production
`grant_aligned_structural_completion_top20_v0_10_0_20260728` run.

## Scientific and data-lineage corrections

- Stage 09 now reads exact candidate protein sequences from the checksum-validated
  `candidate_group_member_sequences.parquet` authority published by Stage 05.
- Each sequence length and SHA-256 value is verified before pocket residues are
  mapped to FASTA coordinates.
- Prepared proteomes and reused OrthoFinder working FASTAs remain explicit
  fallbacks for workflows that do not publish the Stage 05 authority.
- Stage 09 fails closed when selected pockets exist but zero exact sequences are
  resolved, instead of publishing an empty conservation-members table.
- The Stage 09 validation table now reports available and unavailable sequence
  counts.

## Structural asset publication corrections

- Generated ligandability asset paths are rebased from temporary
  `.task_NNNN.running.UUID` locations to stable `task_NNNN` shard locations.
- Every rebased asset is required to exist and match its recorded byte count and
  SHA-256 checksum before the aggregate manifest is published.
- Stage 09b now fails if selected accessions resolve zero structural models or if
  no selected multi-accession group resolves at least two models for comparison.
- Stage 09b validation and provenance now record resolved-model and comparable-group
  counts.

## Test isolation

- `run_tests.sh` now creates an isolated temporary synthetic run and configuration.
  Stale checksum-bound tokens from an earlier release can no longer cause the
  release gate to fail.

## Production recovery

The 559 successful ligandability shards from the existing Dundee run remain
reusable. Stage 09 must be reaggregated with v0.10.2. The old Stage 09b shard
cache must be archived because its completion markers describe zero-model
outputs; Stage 09b and downstream integration must then be rerun.

No scoring threshold, target-species definition, grant gate or experimental
candidate limit is changed by this release.
