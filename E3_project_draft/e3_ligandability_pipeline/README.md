# E3 Ligandability Pipeline

Version 0.1.1

A defensive, auditable replacement for the inherited AlphaFold, FPocket,
P2Rank and pocket-pLDDT scripts used in the ARIA plant E3/PROTAC project.

The workflow is intended for a **small, biologically curated candidate set**.
It is not intended to run blindly across every member of the 1KP-expanded
sequence resource.

## v0.1.1 pocket-mmCIF compatibility fix

Version 0.1.1 separates strict AlphaFold model parsing from tolerant
FPocket pocket-file parsing. FPocket derivative mmCIF files may omit
model-only `_atom_site` columns such as `B_iso_or_equiv`, author numbering
or insertion codes. The pocket parser now requires only a residue name and
at least one usable residue-numbering scheme, excludes hetero atoms from the
protein pocket-residue denominator, and retains explicit label/author mapping
where present. This fixes the Q9SA03 production smoke-test failure observed
with FPocket 4.2.2 output while preserving the strict model pLDDT parser.


## Scientific position

The pipeline produces computational structure and pocket evidence. It does
not establish that a protein is an E3 ligase, that a predicted pocket binds a
small molecule, or that a candidate will work in a PROTAC experiment.

The safe workflow order is:

1. confirm credible E3 family/domain evidence;
2. integrate conservation, orthology and expression;
3. select one primary cluster and two or three backups;
4. curate full-length representative accessions;
5. run this structural workflow on that limited set;
6. review conserved pocket residues and chemistry with the structural team.

## Why the inherited scripts were replaced

The frozen inherited scripts are retained unchanged under
`legacy_reference/`. The replacement addresses material risks in the old
workflow:

- HTTP responses were written directly to final model filenames without
  status, content or atomic-publication checks;
- database writes used append mode and could duplicate rows on rerun;
- the pocket-pLDDT calculation silently discarded unmapped residues through
  an inner join, which could inflate confidence proportions;
- the P2Rank shell script contained a malformed assignment, a hard-coded Mac
  path and no per-accession failure record;
- P2Rank versions differed between inherited analyses;
- the scripts lacked automated tests, structured logging and complete
  provenance.

See `docs/LEGACY_AUDIT_AND_RERUN_DECISION.md` for the formal decision.

## Main capabilities

- reads accessions from plain text, TSV or CSV;
- accepts validated local AlphaFold mmCIF models or queries AlphaFold DB;
- selects a canonical monomer prediction where available;
- downloads model assets using retries, status checks and atomic publication;
- validates and reuses existing files by content rather than filename alone;
- calculates model pLDDT directly from mmCIF residue records;
- compares model-derived quality with API metadata where available;
- runs P2Rank `fpocket-rescore` with an explicit FPocket executable;
- isolates every external-tool run in a staging directory;
- publishes tool output only after command success and output-contract checks;
- parses FPocket and P2Rank output into stable records;
- maps pocket residues using both mmCIF label and author numbering;
- records mapped, ambiguous and unmapped residues explicitly;
- calculates conservative pocket confidence using all predicted pocket
  residues as the denominator;
- writes TSV, compressed Parquet and a self-contained materialised DuckDB;
- writes validation checks, command logs, checksums, versions and a run
  manifest;
- supports inherited model-level pLDDT regression testing.

## Requirements

The supplied Conda environment installs Python dependencies, FPocket and
OpenJDK 17. P2Rank is not redistributed by this package and must be installed
separately. The intended inherited comparison version is P2Rank 2.5.1.

The recovered inherited Micromamba environment pins FPocket 4.2.2. The
supplied cluster environment therefore also pins FPocket 4.2.2, while the
default configuration requires the P2Rank version output to contain `2.5.1`.
FPocket help output, the complete Conda explicit specification and the
no-builds environment export are captured for every shell-wrapper run.

The default P2Rank configuration is `rescore_2024`. P2Rank describes this as
an experimental rescoring model intended for predicted or otherwise
non-crystallographic structures. It should be retained as an explicit method
choice and compared with inherited results rather than treated as a validated
chemical truth.

## Installation on the Dundee cluster

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft

# Place or clone the package as:
# e3_ligandability_pipeline/
cd e3_ligandability_pipeline

conda env create -f environment.cluster.yml
conda activate e3_ligandability
python -m pip install --editable .
```

Install P2Rank 2.5.1 in a stable software directory, for example:

```text
/home/pthorpe001/software/p2rank_2.5.1/prank
```

Copy and edit the configuration rather than modifying the tracked example:

```bash
cp config/config.cluster.example.yaml config/config.cluster.yaml
```

Set:

```yaml
external_tools:
  fpocket_executable: "fpocket"
  p2rank_executable: "/home/pthorpe001/software/p2rank_2.5.1/prank"
```

## Verify the package

```bash
./run_tests.sh
./run_coverage.sh
```

Inspect the actual external tools before a scientific run:

```bash
e3-ligandability inspect-tools \
  --config config/config.cluster.yaml \
  --output analysis/tool_versions.json
```

The command must complete without a version error before production use.

## Input formats

### Plain text

One accession per line:

```text
Q39090
O80608
```

Plain-text input queries AlphaFold DB for each accession.

### TSV with local models

Local models are preferred during inherited-data regression and can avoid
unnecessary downloads:

```text
accession\tmodel_path
Q39090\t/absolute/path/to/AF-Q39090-F1-model_v6.cif
```

Optional input fields include:

- `cif_url`
- `pae_url`
- `msa_url`
- `plddt_url`
- `global_metric_value`
- `fraction_plddt_confident`
- `fraction_plddt_very_high`
- `api_fraction_residues_ge_70`

A local `model_path` is validated and copied into the run output. When
`query_api_for_local_models` is true, AlphaFold metadata are also queried for
comparison, but the local model remains the structural input.

## Run locally or on a login/compute allocation

```bash
./run_e3_ligandability.sh \
  examples/accessions.local_models.example.tsv \
  /home/pthorpe001/data/2026_E3_protac/analysis/ligandability_smoke_20260717 \
  config/config.cluster.yaml \
  e3_ligandability
```

## Submit through Slurm

```bash
./scripts/submit_e3_ligandability_slurm.sh \
  /absolute/path/to/accessions.tsv \
  /home/pthorpe001/data/2026_E3_protac/analysis/ligandability_shortlist_v1 \
  config/config.cluster.yaml \
  e3_ligandability
```

Defaults are `barton`, `general`, 8 CPUs, 32G RAM and 12 hours. They can be
changed through the documented `E3_SLURM_*` environment variables.

## Validate the inherited test set first

The first real cluster task is model-level regression against the retained
inherited testing folder:

```bash
./run_legacy_regression.sh \
  /home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data/Other_things/Drost_lab_ligandability/data/testing \
  /home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data/Other_things/Drost_lab_ligandability/data/testing/testing_af_metadata.csv \
  /home/pthorpe001/data/2026_E3_protac/analysis/ligandability_legacy_model_regression_20260717
```

This validates model-derived pLDDT against inherited metadata. It does not by
itself validate inherited FPocket/P2Rank parsing; that requires a controlled
one- or two-model end-to-end smoke run and comparison with the retained raw
outputs.

## Outputs

```text
OUTPUT_DIR/
├── duckdb/e3_ligandability.duckdb
├── logs/
├── models/<accession>/
├── provenance/run_manifest.json
├── tables/
│   ├── parquet/
│   └── tsv/
└── tool_outputs/<accession>/
```

The DuckDB contains materialised tables and is not tied to source Parquet
paths on the external hard drive.

See:

- `docs/OUTPUT_SCHEMA.md`
- `docs/METHODS_AND_SCIENTIFIC_LIMITS.md`
- `docs/CLUSTER_RUNBOOK.md`

## Exit codes

- `0`: workflow and validation succeeded;
- `1`: configuration, input, preflight or unexpected command failure;
- `2`: outputs were produced but one or more accessions or validation checks
  did not pass;
- `64`, `66`, `69`: shell-wrapper usage, missing-input or environment errors.

## Release validation

Version 0.1.1 includes:

- 83 passing automated tests;
- 97% branch-aware source coverage;
- named test traceability for all 107 production functions;
- full and reduced FPocket-style synthetic mmCIF fixtures;
- malformed reduced-pocket mmCIF rejection tests;
- fake-executable FPocket/P2Rank command tests;
- command-line end-to-end tests;
- inherited-script checksum protection;
- branch-aware coverage with a 95% release threshold;
- PEP 8 checking at 88 characters;
- PEP 257-compatible Google-style docstrings;
- `bash -n` validation for every production shell script;
- isolated wheel installation and dependency validation;
- source distribution and wheel metadata validation with Twine.

The real Q9SA03 FPocket/P2Rank command completed under v0.1.0, but output
parsing stopped safely on a reduced FPocket mmCIF before any pocket tables
were published. Version 0.1.1 fixes that parser defect. Scientific
pocket-level validation still requires rerunning the Q9SA03 smoke test and
reviewing residue mapping and agreement with the inherited outputs.
