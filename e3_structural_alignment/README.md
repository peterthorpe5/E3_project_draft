# E3 structural alignment

This package tests whether selected predicted pockets occupy a comparable three-dimensional
position after protein-structure superposition. It is a separate component of the ARIA E3
workflow, not an extension hidden inside a shell script.

The package uses both US-align and TM-align for global protein superposition. For each candidate
group it selects a deterministic best-evidence reference structure, aligns every other compatible
model to that reference with both tools, reads each rotation/translation matrix and transforms the
mobile pocket C-alpha coordinates into the reference frame. A member is counted as supported only
when every enabled aligner passes the configured global and pocket thresholds. It then reports:

- both length-normalised TM-scores, aligned length, RMSD and sequence identity;
- the exact matrix and unmodified output from each tool for every comparison;
- reference/mobile pocket C-alpha counts;
- pocket-centroid distance;
- each pocket's fraction of residues within the configured distance of the other pocket;
- symmetric pocket-overlap fraction and mean bidirectional nearest-residue distance; and
- pair- and group-level threshold decisions, plus pairwise tool agreement.

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

The environment pins the Bioconda US-align build at `20241201` and TM-align at `20240303`.
Executable versions are recorded in every run manifest because alternative builds may change
numerical output.

## Standalone run

The normal entry point uses named options only:

```bash
./run_e3_structural_alignment.sh \
    --selected-pockets /path/to/selected_pockets.parquet \
    --pocket-residue-mappings /path/to/reused_pocket_residue_mappings.parquet \
    --asset-manifest /path/to/reused_asset_manifest.parquet \
    --output-dir /path/to/structural_alignment_result \
    --usalign-executable USalign \
    --tmalign-executable TMalign \
    --threads 16 \
    --distance-threshold-angstrom 4.0 \
    --maximum-centroid-distance-angstrom 8.0 \
    --minimum-pocket-overlap-fraction 0.5 \
    --minimum-global-tm-score 0.5 \
    --minimum-group-support-fraction 0.75 \
    --resume
```

The output directory is published atomically. `--resume` succeeds only when the input checksums,
settings, output sizes and output checksums match the completed manifest. An existing mismatched
directory fails closed; `--force` is required for an intentional replacement and preserves the
previous directory under a unique `superseded` name.

## Input contracts

`selected_pockets` must contain one selected pocket per cluster/accession with at least:

- `cluster_id`
- `primary_group_type`
- `primary_group_id`
- `candidate_accession`
- `species_column`
- `pocket_number`

The residue mapping table must contain `accession`, `pocket_number` and `mapping_status`, plus
model label and/or author residue identifiers. Only `MAPPED` rows for the selected pocket are used.

The asset manifest must contain `accession` and at least one of `path`, `model_path` or
`source_path`. Existing `.pdb`, `.cif` and `.mmcif` models are recognised. A supplied SHA-256 is
verified before use. Missing models or pocket coordinates become explicit
`INSUFFICIENT_STRUCTURES` group evidence; malformed inputs, checksum changes or an unexpected
structural-aligner failure stop an enabled run. Either backend can be intentionally disabled with
`--skip-usalign` or `--skip-tmalign`, but at least one must remain enabled.

## Output contract

```text
structural_alignment_result/
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
    ├── structural_alignment_summary.tsv
    └── structural_alignment_summary.parquet
```

TSV is the human-readable exchange format; typed Parquet is the integration authority. No
comma-separated analytical outputs are produced.

## End-to-end integration

The master workflow owns stage ordering and Slurm resources. In an end-to-end YAML,
`09b_structural_alignment` may be:

- disabled and optional, producing a valid `skipped_optional` stage manifest; or
- enabled with the supplied argument-vector adapter, producing the tables above.

Downstream integration always completes. When the stage is skipped, final tables state
`three_dimensional_alignment_status=NOT_ASSESSED`; this is not interpreted as evidence that the
pockets differ. The independent pairwise comparisons run concurrently within the CPU allocation of
the single structural stage. A later Foldseek screening backend can be added behind the same table
contract if the post-shortlist structure set becomes much larger.
