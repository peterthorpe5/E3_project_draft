# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.1.4

<!-- source: RELEASE_NOTES_v0_1_4.md; sha256: 917e7eda9eb1fd0643db33940cebc15122ac48091ba4bbd9df64bd4197f837a8 -->

- Adds `candidate_group_member_sequences.tsv` and typed Parquet for every member of each
  candidate-relevant orthogroup or hierarchical orthogroup.
- Reports the run-scoped OrthoFinder group identifier, source species, internal sequence ID,
  original FASTA identifier, parsed accession/entry, candidate links, review status, sequence
  length, sequence SHA-256 and full amino-acid sequence.
- Reads only the candidate-relevant internal sequences from OrthoFinder `WorkingDirectory`
  `Species*.fa` files, avoiding an unnecessary all-proteome sequence export.
- Includes the exact OrthoFinder working FASTA files in stage checksums so resume cannot silently
  reuse a sequence table generated from changed input proteins.

## v0.1.3

<!-- source: RELEASE_NOTES_v0_1_3.md; sha256: 0831ee6a41ecd05c640b531f50b1a8404b5d6ffb57c34eea160e549247a0830c -->

### Resolved defects

- Replaced invalid standard-logging placeholders such as `%,d` with safely formatted grouped
  counts. Progress messages such as `1,250,000 records` no longer emit logging tracebacks.
- Removed an inherited `SLURM_CPUS_PER_TASK` value before calling `sbatch`. This matters when a
  submission is made from an interactive Slurm job with a different CPU allocation.
- Added a compute-node guard that compares the independently exported request with
  `SLURM_CPUS_PER_TASK` and fails before analysis if they differ.
- Made the submitter infer pipeline `--threads` from `--cpus-per-task` when omitted and reject an
  explicit mismatch.
- Preserved a YAML-configured thread value when local execution omits the CLI override.
- Connected `execution.threads` to the PyArrow compute and I/O thread pools.

### Scientific impact

The completed Results_Feb26 outputs from v0.1.2 remain valid. This release changes logging and
resource control only; identifier parsing, mapping tiers, orthogroup membership, regression checks
and publication contracts are unchanged.

### Verification target

The complete configured suite contains 42 tests and retains the 95% branch-aware coverage gate.
