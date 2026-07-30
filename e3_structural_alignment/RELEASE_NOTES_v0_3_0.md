# e3_structural_alignment v0.3.0

Version 0.3.0 adds an additive, post-run visual review layer for project-lead
selection from the authoritative Stage 10 ranked shortlist. It does not
recalculate scores, candidate order, strict pocket calls or top-k sensitivity
conclusions.

The new `e3-pocket-review` command:

- discovers the completed Stage 09, 09b and 10 authorities from `--run-root`;
- preserves `final_evolutionary_rank` and reports the ordered top 50 by default;
- writes one self-contained HTML page per evolutionary group;
- embeds rotatable C-alpha traces for every available group-member model;
- highlights the strict rank-one pocket and retained rank-two to rank-five
  alternatives separately;
- projects exact one-based Stage 09 FASTA pocket coordinates onto the published
  MAFFT sequence alignment;
- shows the complete authoritative ranking record and strict/top-k structural
  summaries for manual scrutiny;
- writes a top-level searchable index, a blank TSV decision worksheet, QC,
  checksums, logs and a checksum-bound run manifest;
- writes a rank-preserving evidence matrix, an exact pocket-residue annotation
  audit and a checksum-aware protein-model inventory;
- makes the evidence matrix searchable/filterable and adds interactive linear
  pocket-position tracks alongside the residue-level alignment;
- supports validated `--resume` and controlled `--force` publication; and
- includes a bounded Slurm submitter that defaults to account and partition
  `barton` and rejects wall times above five days.

All HTML is offline and contains no external JavaScript or network dependency.
The structure panel is explicitly labelled as a C-alpha trace, not an atomistic
surface, docking calculation or binding result.
