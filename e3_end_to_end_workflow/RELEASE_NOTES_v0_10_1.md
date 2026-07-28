# e3_end_to_end_workflow v0.10.1

## Stage 09 FASTA-coordinate aggregation hotfix

Version 0.10.1 fixes a Stage 09 aggregation failure observed after the
distributed ligandability campaign completed successfully.

### Corrected behaviour

- Import Python's `math` module before using `math.inf` as the deterministic
  sort value for residues without an exact FASTA coordinate.
- Retain residues whose model-to-FASTA mapping is unavailable and sort them
  after residues with validated integer coordinates.
- Add a regression case covering `fasta_position=None` and the
  `LABEL_SEQUENCE_ID_UNAVAILABLE` status.

### Resume contract

- No configuration, shortlist, component output or completed shard is changed.
- The existing v0.10.0 structural run can be resumed in place.
- Checksum-valid Stage 09 ligandability shards remain reusable.
- Stage 09 aggregation reruns and publishes its outputs atomically before
  Stage 09b begins.
