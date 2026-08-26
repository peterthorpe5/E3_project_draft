# E3 structural alignment

This package tests whether selected predicted pockets occupy a comparable three-dimensional
position after protein-structure superposition. It is a separate component of the ARIA E3
workflow, not an extension hidden inside a shell script.

The package uses both US-align and TM-align for global protein superposition. For each candidate
group it selects a deterministic best-evidence reference structure, aligns every other compatible
model to that reference with both tools, reads each rotation/translation matrix and transforms the
mobile pocket C-alpha coordinates into the reference frame. It answers two related but distinct
questions:

1. Does the selected pocket occupy the same part of the global protein fold?
2. Is the local pocket residue environment structurally and chemically conserved?

A member is counted as supported only when every enabled aligner passes the thresholds relevant to
the conclusion. Version 0.2.0 also supports a separate sensitivity analysis: the selected
reference pocket is compared with the top-k member pockets, and US-align and TM-align must support
the same member pocket number. This never overwrites the rank-one result. The package reports:

- both length-normalised TM-scores, aligned length, RMSD and sequence identity;
- the exact matrix and unmodified output from each tool for every comparison;
- reference/mobile pocket C-alpha counts;
- pocket-centroid distance;
- each pocket's fraction of residues within the configured distance of the other pocket;
- symmetric pocket-overlap fraction and mean bidirectional nearest-residue distance;
- mutual-nearest local pocket-residue correspondences, sequence identity and chemical-group
  conservation;
- validated one-based FASTA coordinates where the exact model residue can be reconciled to the
  exact protein sequence;
- separate pair/group same-position and conserved-pocket decisions, plus tool agreement;
- a self-contained graphical HTML report; and
- an offline interactive browser for every US-align/TM-align superposition.

These are computational structural predictions. A supported comparison does not prove ligand
binding, selectivity, E3 activity or target degradation.

## Installation

Create the independent environment and install the package:

```bash
cd e3_structural_alignment
conda env create --file environment.yml
conda activate e3_structural_alignment
python -m pip install --no-deps --editable .
./run_tests.sh
```

`run_tests.sh` also adds this checkout's `src/` directory to `PYTHONPATH`, so a
freshly created environment can run the source tests before the editable install.
The editable install is still required for the `e3-structure-align` command-line
entry point.

The environment pins the Bioconda US-align build at `20241201` and TM-align at `20240303`.
Executable versions are recorded in every run manifest because alternative builds may change
numerical output.

## Standalone run

The normal entry point uses named options only:

```bash
./run_e3_structural_alignment.sh \
    --selected-pockets /path/to/selected_pockets.parquet \
    --ranked-pockets /path/to/ranked_member_pockets.parquet \
    --pocket-residue-mappings /path/to/reused_pocket_residue_mappings.parquet \
    --pocket-sequence-coordinates /path/to/pocket_sequence_coordinates.parquet \
    --ranked-pocket-sequence-coordinates \
      /path/to/ranked_pocket_sequence_coordinates.parquet \
    --asset-manifest /path/to/reused_asset_manifest.parquet \
    --reference-manifest /path/to/preserved_group_references.tsv \
    --output-dir /path/to/structural_alignment_result \
    --usalign-executable USalign \
    --tmalign-executable TMalign \
    --threads 16 \
    --member-pocket-top-k 5 \
    --distance-threshold-angstrom 4.0 \
    --maximum-centroid-distance-angstrom 8.0 \
    --minimum-pocket-overlap-fraction 0.5 \
    --minimum-global-tm-score 0.5 \
    --minimum-structural-residue-match-fraction 0.5 \
    --minimum-structural-chemical-group-conservation 0.6 \
    --minimum-group-support-fraction 0.75 \
    --resume
```

The output directory is published atomically. `--resume` succeeds only when the input checksums,
settings, output sizes and output checksums match the completed manifest. An existing mismatched
directory fails closed; `--force` is required for an intentional replacement and preserves the
previous directory under a unique `superseded` name.

`--reference-manifest` is optional for normal analysis. When supplied, it must
identify exactly one eligible reference accession for every analysed group.
The human-and-plant extension uses this contract to retain the plant reference
selected by the original analysis rather than selecting a new reference after
human structures are added.

## Input contracts

`selected_pockets` must contain one selected pocket per cluster/accession with at least:

- `cluster_id`
- `primary_group_type`
- `primary_group_id`
- `candidate_accession`
- `species_column`
- `pocket_number`

`ranked_pockets` is optional and contains the same identifiers plus `selection_rank`. When it is
provided, ranks up to `--member-pocket-top-k` are assessed. If it is omitted, the strict selected
pockets are treated as rank one and the sensitivity result is identical to the primary result.

The residue mapping table must contain `accession`, `pocket_number` and `mapping_status`, plus
model label and/or author residue identifiers. Only `MAPPED` rows for the selected pocket are used.

The optional pocket sequence-coordinate table is generated by stage 09 of the master workflow. It
must include accession, pocket number, model residue locators, mapping status and the validated
one-based FASTA position/residue. FASTA positions are used only for `MAPPED_EXACT` records. The
structural package never treats author residue numbers as sequence positions and never guesses
through missing residues or insertion codes.

The asset manifest must contain `accession` and at least one of `path`, `model_path` or
`source_path`. Existing `.pdb`, `.cif` and `.mmcif` models are recognised. A supplied SHA-256 is
verified before use. Missing models or pocket coordinates become explicit
`INSUFFICIENT_STRUCTURES` group evidence; malformed inputs, checksum changes or an unexpected
structural-aligner failure stop an enabled run. Either backend can be intentionally disabled with
`--skip-usalign` or `--skip-tmalign`, but at least one must remain enabled.

## Output contract

```text
structural_alignment_result/
├── reports/structural_alignment_summary.html
├── interactive/structural_alignment_browser.html
├── interactive/pairs/<tool>/<group>/<reference>__<member>.html
├── logs/pipeline.log
├── provenance/run_manifest.json
├── qc/structural_alignment_validation.tsv
├── raw/us-align/<group>/<reference>__<mobile>.matrix.txt
├── raw/us-align/<group>/<reference>__<mobile>.stdout.txt
├── raw/tm-align/<group>/<reference>__<mobile>.matrix.txt
├── raw/tm-align/<group>/<reference>__<mobile>.stdout.txt
└── tables/
    ├── structural_alignments.tsv
    ├── structural_alignments.parquet
    ├── pocket_comparisons.tsv
    ├── pocket_comparisons.parquet
    ├── pocket_residue_matches.tsv
    ├── pocket_residue_matches.parquet
    ├── structural_alignment_summary.tsv
    ├── structural_alignment_summary.parquet
    ├── structural_pocket_sensitivity_comparisons.tsv
    ├── structural_pocket_sensitivity_comparisons.parquet
    ├── structural_pocket_sensitivity_residue_matches.tsv
    ├── structural_pocket_sensitivity_residue_matches.parquet
    ├── structural_pocket_sensitivity_member_summary.tsv
    ├── structural_pocket_sensitivity_member_summary.parquet
    ├── structural_pocket_sensitivity_group_summary.tsv
    └── structural_pocket_sensitivity_group_summary.parquet
```

TSV is the human-readable exchange format; typed Parquet is the integration authority. No
comma-separated analytical outputs are produced.

## HTML reports and interactive browsing

`reports/structural_alignment_summary.html` is the concise scientific report. It contains:

- assessed/unassessed group and comparison counts;
- an SVG plot of mean minimum TM-score against pocket overlap;
- group-level same-position and conserved-pocket conclusions;
- pairwise US-align/TM-align evidence and agreement;
- residue-level structural/sequence correspondences;
- every decision threshold, executable version and controlled-input checksum; and
- explicit interpretation guidance and limitations.

`interactive/structural_alignment_browser.html` is a searchable index of pairwise views. Each view
embeds the reference C-alpha trace and the transformed member trace, with the reference and member
pockets marked in different colours. It supports drag rotation, wheel zoom, fit/reset controls,
independent structure/pocket visibility and clickable residue labels. The pages are standalone and
contain no external JavaScript or network dependency, so the whole result directory can be copied
from the cluster and opened locally. These views show C-alpha traces and selected residues; they do
not claim to be an atomistic surface or docking viewer.

Pocket-review publication in version 0.5.0 checksum-validates and copies these
exact pairwise superposition pages into the portable bundle, with a
`tables/structural_alignment_viewers.tsv` index. The Python app therefore opens
the analysis-derived transforms directly and does not reconstruct or
cosmetically approximate an alignment in Streamlit.

## Ranked top-50 pocket-review report

Version 0.3.0 adds an additive post-run report for project-lead manual review. It reads the
authoritative Stage 10 order and existing Stage 09/09b evidence; it does not recalculate candidate
scores, reorder groups or replace the strict rank-one conclusion with top-k sensitivity evidence.

```bash
./run_e3_pocket_review.sh \
    --run-root /path/to/completed/e3_end_to_end_run \
    --output-dir /path/to/completed/e3_end_to_end_run/pocket_review_top50 \
    --review-limit 50 \
    --member-pocket-top-k 5 \
    --resume
```

The command discovers the conventional Parquet or TSV authorities below the run root. Every path
can also be supplied explicitly through a named option when a portable copied run uses a different
layout. The output is published atomically and includes:

```text
pocket_review_top50/
├── index.html
├── evidence_matrix.html
├── groups/rank_001__<group-type>__<group-id>.html
├── review_decisions_template.tsv
├── sequences/
│   └── prioritised_group_sequences.fasta
├── tables/
│   ├── review_report_index.tsv
│   ├── top_group_evidence_matrix.tsv
│   ├── pocket_residue_annotations.tsv
│   ├── protein_model_inventory.tsv
│   ├── prioritised_group_sequences.tsv
│   └── structural_alignment_viewers.tsv
├── structural_alignment/groups/<group>/pairs/<tool>/...html
├── qc/pocket_review_validation.tsv
├── logs/pocket_review.log
└── provenance/run_manifest.json
```

Each group page contains:

- a rotatable C-alpha trace for every available member model;
- separately coloured strict rank-one and rank-two to rank-five pocket residues;
- the published MAFFT sequence alignment with exact Stage 09 pocket coordinates highlighted;
- an interactive linear alignment-position track for rapid pocket-location comparison;
- browser-side PDF downloads for the current rotated 3D canvas and the complete
  multi-page MAFFT alignment, without a CDN or remote rendering service;
- the complete authoritative ranking row;
- strict structural and top-k sensitivity summaries; and
- an explicit warning that predicted pocket location does not establish ligand binding, E3
  recruitment or complete PROTAC function.

The searchable and filterable evidence matrix compares the primary and sensitivity conclusions
across all ranked groups without creating a new score. The residue-audit TSV records exact FASTA,
alignment and structure coordinates for every highlighted residue, while the model inventory
records availability and checksums for every displayed protein. Summary cards on the index show
group, protein, model and alignment coverage.

The prioritised-group sequence exports retain every record from each authoritative Stage 09
alignment, including group members without ranked-pocket or structure evidence. The FASTA contains
ungapped full protein sequences with unique rank-and-group identifiers. The matching TSV provides
the original accession/name, species when available, evolutionary-group and lead-cluster
identifiers, reference and pocket-evidence flags, sequence length, ungapped sequence, original
aligned sequence and alignment checksum.

The production HTML index also summarises pre-structure rank/pass state, target- and
structural-species coverage, minimum member druggability, integrated score, strict and top-k 3D
position/conservation outcomes, sequence/model coverage and formal final-pass counts. Each group
page includes the complete decision reasons, missing-evidence record, sequence/model inventory,
expanded structural metrics and links to every downloadable audit resource.

All page data, CSS and JavaScript are embedded. No network connection, CDN or remote structure
service is used. The report can therefore be copied from the cluster and opened directly on a Mac.

The Slurm submitter defaults to the University of Dundee `barton` account and `barton` partition:

```bash
./scripts/submit_e3_pocket_review_slurm.sh \
    --run-root /path/to/completed/e3_end_to_end_run \
    --output-dir /path/to/completed/e3_end_to_end_run/pocket_review_top50 \
    --account barton \
    --partition barton \
    --review-limit 50 \
    --member-pocket-top-k 5 \
    --resume
```

The submitter rejects wall times above five days. Its default request is four CPUs, 16 GB and four
hours; report generation is normally much smaller than the structural comparison campaign because
it reuses all completed models, alignments and tables.

## End-to-end integration

The master workflow owns stage ordering and Slurm resources. In an end-to-end YAML,
`09b_structural_alignment` may be:

- disabled and optional, producing a valid `skipped_optional` stage manifest; or
- enabled with the supplied argument-vector adapter, producing the tables and HTML resources above.

Downstream integration always completes. When the stage is skipped, final tables state
`three_dimensional_alignment_status=NOT_ASSESSED`; this is not interpreted as evidence that the
pockets differ. The independent pairwise comparisons run concurrently within the CPU allocation of
the single structural stage. A later Foldseek screening backend can be added behind the same table
contract if the post-shortlist structure set becomes much larger.
