# Changelog

This changelog consolidates the package's historical release notes. Entries are ordered from newest to oldest.

<!-- generated-by: consolidate_release_notes.py -->

## v0.6.0

- Retains explicitly identified residue-level pLDDT from ModelCIF local quality
  records in C-alpha coordinate objects and portable group/pair viewer payloads.
- Does not reinterpret generic PDB or mmCIF crystallographic B-factors as
  AlphaFold confidence.
- Fails explicitly for malformed, out-of-range or contradictory declared pLDDT
  values while leaving models without local quality records fully supported.

## v0.5.0

- Adds an explicit group-reference manifest so additive comparisons can retain
  an established plant reference.
- Copies checksum-validated pairwise structural-superposition pages into each
  portable pocket-review bundle and publishes their exact viewer index.
- Supports an optional checksum-bound supplementary sequence inventory and
  FASTA for members lacking assessable structures or pockets.

## v0.4.0

<!-- source: RELEASE_NOTES_v0_4_0.md; sha256: 183d45b0b4ef5cca8a895d929b3fdae8074e9c5c62611e735dc046af2ad63f12 -->

- Adds offline **Download current view PDF** and **Download alignment PDF**
  controls to every generated selected-group review page.
- The 3D PDF records the current protein, pocket, rotation and zoom shown in the
  C-alpha viewer. The alignment export paginates the complete published MAFFT
  alignment as monospaced vector text.
- Both exports are produced in the browser with embedded JavaScript and retain
  the report's no-CDN, offline portability contract.

## v0.3.2

<!-- source: RELEASE_NOTES_v0_3_2.md; sha256: 2382bde966c593a8c7d624f65307818099d0e4ae00f2e0cd67d6e107851c2da8 -->

This reporting-only patch does not recalculate structures, pockets, alignments,
scores, thresholds or candidate decisions.

- The structure viewer's **Fit structure** control is renamed **Fit and centre**.
- The action now restores the default orientation as well as the auto-fit zoom,
  so it remains visibly useful after rotation or zoom.
- An accessible live status message confirms that fitting and centring completed.
- **Reset rotation** now changes orientation only, keeping its purpose distinct
  from the full fit-and-centre action.
- Regression assertions cover the control label, complete reset handler and
  accessible confirmation region.

## v0.3.1 — SLURM PATH HOTFIX 20260731

<!-- source: RELEASE_NOTES_v0_3_1_SLURM_PATH_HOTFIX_20260731.md; sha256: 128ffad4583fe657675e4641527161fa9f529ee0d4c400a0cacdd474b1cc64ed -->

### Summary

The pocket-review Slurm submitter now passes the absolute package root to the
worker explicitly. This prevents Slurm's copied worker script from incorrectly
resolving `run_e3_pocket_review.sh` beneath `/var/spool/slurmd`.

### Scope

- No scientific calculations, ranking logic, thresholds or report contents
  changed.
- Existing completed end-to-end runs remain valid and do not need to be rerun.
- A failed pocket-review report job can be resubmitted safely with `--resume`.

### Validation

The regression test executes a copy of the worker from a simulated
`/var/spool/slurmd` directory and verifies that it invokes the runner from the
explicit package root.

## v0.3.1

<!-- source: RELEASE_NOTES_v0_3_1.md; sha256: 4134d41770e761cfca8ed9774821785bf136a1941f09fe15092d93fe13469813 -->

Date: 30 July 2026

### Additive sequence export

The ranked pocket-review report now publishes two explicit sequence resources:

- `sequences/prioritised_group_sequences.fasta`: a combined, ungapped protein
  FASTA for every sequence in each reviewed group alignment;
- `tables/prioritised_group_sequences.tsv`: a tab-separated audit table
  containing rank, evolutionary-group and lead-cluster identifiers, original
  accession/name, species when available, reference and ranked-pocket-evidence
  flags, sequence length, ungapped sequence, aligned sequence and the source
  alignment checksum.

The export uses the authoritative Stage 09 `aligned.fasta` files and retains
alignment members even when no ranked pocket or structural model is available.
It does not alter group ranking, pocket selection, structural comparison or any
candidate decision.

### Expanded production HTML

The top-level ranked index now exposes the evidence needed for rapid manual
triage rather than requiring reviewers to open several separate tables:

- pre-structure rank and pass state;
- target- and structural-species coverage;
- minimum member druggability and integrated score;
- strict and top-k 3D position and conservation conclusions;
- sequence, pocket-evidence and model coverage;
- formal final-pass counts and direct audit-file downloads.

Each group page now includes the configured gate components, decision and
missing-evidence reasons, a complete sequence/model inventory, expanded
residue-level structural metrics and direct links to every downloadable audit
resource.

### Production input compatibility

Automatic input discovery now prefers the stable
`top_computational_review_shortlist.parquet` authority and accepts normal
production directories containing both Parquet and TSV copies. This resolves a
v0.3.0 discovery defect that could reject a valid completed workflow because
both formats were present.

### Validation

Regression tests cover:

- combined TSV and FASTA publication;
- deterministic identifiers and output order;
- removal of alignment gaps from exported protein sequences;
- retention and explicit flagging of alignment members without pocket evidence;
- rejection of all-gap sequences, empty exports and invalid FASTA line widths;
- deterministic Parquet preference when production TSV/Parquet pairs coexist;
- expanded summary, group-level evidence and download links in the HTML;
- checksum-bound resume behaviour for the new outputs.

## v0.3.0

<!-- source: RELEASE_NOTES_v0_3_0.md; sha256: aa10ebe88c5c794a073a4903a653d42554f392f9b7e614257a4623e4940ccb80 -->

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

## v0.2.0

<!-- source: RELEASE_NOTES_v0_2_0.md; sha256: 86cbee9bc687d7e6bda0ec2fa7bb8f1a443e767680f165c2df03c2d28d8255ae -->

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

## v0.1.2

<!-- source: RELEASE_NOTES_v0_1_2.md; sha256: 0d6c973681e5b7eacda652e766ec428a4dd19155ea31dd90b8f1dd68a6cb064e -->

- `run_tests.sh` now resolves the repository's `src/` package automatically.
- A newly created conda environment can run the tests without first failing with
  `ModuleNotFoundError: No module named 'e3structalign'`.
- The editable installation remains the supported way to publish the
  `e3-structure-align` command-line entry point.
- All 25 structural-alignment tests pass at 91% branch-aware coverage.

## v0.1.1

<!-- source: RELEASE_NOTES_v0_1_1.md; sha256: 3d7b868c94f294b55bc3fe59ebb40e6f16408703bdc8ef7cae96ce3887ed1ecc -->

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

## v0.1.0

<!-- source: RELEASE_NOTES_v0_1_0.md; sha256: ea801e04eb538f09d3059386dc6e725844679ab28a7b14a1a190f056c7648476 -->

- Adds checksum-bound PDB/mmCIF model resolution from retained ligandability asset manifests.
- Uses both US-align and TM-align to superpose every eligible group member to a deterministic
  reference model, requiring consensus across enabled tools for group support.
- Preserves raw standard output and the rotation/translation matrix for each comparison.
- Measures selected-pocket centroid separation, symmetric residue-neighbour overlap and mean
  bidirectional nearest-residue distance after superposition.
- Publishes paired TSV/Parquet evidence tables, group summaries, formal validation and a complete
  SHA-256 run manifest.
- Supports bounded concurrency, atomic publication, explicit resume/force behaviour, file/console
  logging and retained failed staging directories.
- Treats missing compatible structures as unavailable evidence rather than a biological negative.
