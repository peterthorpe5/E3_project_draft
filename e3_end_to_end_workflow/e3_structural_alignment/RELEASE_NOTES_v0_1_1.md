# E3 structural alignment v0.1.1

- Adds a self-contained scientific HTML summary with overview counts, explicit same-position and
  conserved-pocket conclusions, an SVG TM-score/pocket-overlap plot, group and pair evidence
  tables, residue correspondences, thresholds, aligner versions, input checksums and interpretation
  limits.
- Adds a portable interactive HTML browser. Each US-align/TM-align comparison has a rotatable,
  zoomable C-alpha superposition with independently switchable reference/member traces and
  highlighted pocket residues. Clicking a residue reports its chain, structure identifier and
  residue name. No web service or network connection is required.
- Separates the scientific questions “is the pocket in the same 3D position?” and “is its local
  residue environment structurally conserved?” rather than collapsing them into one score.
- Adds mutual-nearest pocket-residue correspondences after superposition, with configurable local
  match and chemical-group conservation thresholds.
- Accepts validated pocket-to-FASTA coordinate mappings and carries sequence positions and amino
  acids into the residue-level structural table and interactive evidence.
- Publishes `pocket_residue_matches.tsv` and typed Parquet alongside the existing alignment,
  comparison and group-summary tables.
- Retains one interactive view for every enabled aligner so US-align and TM-align evidence can be
  inspected independently.
