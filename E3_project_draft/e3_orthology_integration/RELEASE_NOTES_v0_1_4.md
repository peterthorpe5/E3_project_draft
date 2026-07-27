# E3 orthology integration v0.1.4

- Adds `candidate_group_member_sequences.tsv` and typed Parquet for every member of each
  candidate-relevant orthogroup or hierarchical orthogroup.
- Reports the run-scoped OrthoFinder group identifier, source species, internal sequence ID,
  original FASTA identifier, parsed accession/entry, candidate links, review status, sequence
  length, sequence SHA-256 and full amino-acid sequence.
- Reads only the candidate-relevant internal sequences from OrthoFinder `WorkingDirectory`
  `Species*.fa` files, avoiding an unnecessary all-proteome sequence export.
- Includes the exact OrthoFinder working FASTA files in stage checksums so resume cannot silently
  reuse a sequence table generated from changed input proteins.
