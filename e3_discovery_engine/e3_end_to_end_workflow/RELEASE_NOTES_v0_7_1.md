# E3 end-to-end workflow v0.7.1

- Extends optional stage `09b_structural_alignment` with separate same-position and conserved-pocket
  conclusions, local residue matching and chemical-group conservation.
- Publishes a self-contained graphical structural report and an offline interactive browser with
  marked pocket residues for every US-align/TM-align comparison.
- Maps pocket residues back to one-based FASTA coordinates only when model label numbering, range
  and amino-acid identity all validate. Unmappable residues remain explicit rather than guessed.
- Adds `pocket_sequence_coordinates.tsv` and typed Parquet to stage 09.
- Carries structural residue correspondences, position status and local conservation summaries into
  the integrated DuckDB and final candidate resource.
- Adds explicit OrthoFinder orthogroup and hierarchical-group identifiers to final candidate
  records.
- Adds a candidate-relevant group-member sequence table with OrthoFinder identifiers, species,
  original protein identifiers, candidate links, sequence length, SHA-256 and full amino-acid
  sequence.
- Preserves backward compatibility: configurations without `09b_structural_alignment` still publish
  an explicit optional skip and complete the downstream workflow.
