# Dundee cluster runbook

## Permanent project locations

```text
Project root
/home/pthorpe001/data/2026_E3_protac

Curated integration workspace
/home/pthorpe001/data/2026_E3_protac/E3_PROTAC_curated

Validated sequence resource
/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results/full_onekp_plus_v0_1_14_20260715_100551

Legacy ligandability source and testing data
/home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data/Other_things/Drost_lab_ligandability
```

The old dated curated path is a symlink to `E3_PROTAC_curated`. New scripts
should use the permanent path.

## Create the environment

```bash
cd /home/pthorpe001/data/2026_E3_protac/E3_project_draft/e3_ligandability_pipeline

conda env create -f environment.cluster.yml
conda activate e3_ligandability
python -m pip install --editable .
```

The wrapper uses `conda run`; it does not rely on `conda activate` working in a
non-interactive Slurm shell.

## Configure P2Rank

Install P2Rank 2.5.1 in a stable read-only software path. Copy the example
configuration and set the absolute `prank` path.

```bash
cp config/config.cluster.example.yaml config/config.cluster.yaml
```

Check tools:

```bash
e3-ligandability inspect-tools \
  --config config/config.cluster.yaml \
  --output /home/pthorpe001/data/2026_E3_protac/analysis/ligandability_tool_versions_20260717.json
```

Review both the JSON and log. Do not submit a scientific run if the command
fails or the P2Rank version is not the intended version.

## Package validation

```bash
./run_tests.sh
./run_coverage.sh
```

## Inherited model regression

```bash
LEGACY_ROOT="/home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data/Other_things/Drost_lab_ligandability"

./run_legacy_regression.sh \
  "${LEGACY_ROOT}/data/testing" \
  "${LEGACY_ROOT}/data/testing/testing_af_metadata.csv" \
  "/home/pthorpe001/data/2026_E3_protac/analysis/ligandability_legacy_model_regression_20260717"
```

A non-zero exit means at least one retained model does not reproduce the
inherited model-level metadata within the configured tolerances. Inspect the
TSV; do not relax tolerances merely to obtain a pass.

## Controlled end-to-end smoke run

Create a TSV containing one or two retained local models. Use absolute paths.

```text
accession\tmodel_path
A8MQJ8\t/absolute/path/to/AF-A8MQJ8-F1-model_v6.cif
```

Submit:

```bash
./scripts/submit_e3_ligandability_slurm.sh \
  /absolute/path/to/smoke_accessions.tsv \
  /home/pthorpe001/data/2026_E3_protac/analysis/ligandability_smoke_20260717 \
  config/config.cluster.yaml \
  e3_ligandability
```

After completion:

```bash
sacct -j JOB_ID \
  --format=JobID,JobName,State,Elapsed,TotalCPU,AllocCPUS,MaxRSS,ExitCode
```

Review:

- `tables/tsv/accession_status.tsv`
- `tables/tsv/model_quality.tsv`
- `tables/tsv/fpocket_pockets.tsv`
- `tables/tsv/p2rank_pockets.tsv`
- `tables/tsv/pocket_residue_mappings.tsv`
- `tables/tsv/pocket_quality.tsv`
- `tables/tsv/validation.tsv`
- `provenance/run_manifest.json`
- per-accession external-tool stdout/stderr.

## Production shortlist run

Do not begin until family/domain, orthology, conservation and expression review
has selected the primary and backup clusters. Use curated full-length stable
accessions, not unreviewed 1KP fragments.

Create a new output directory for each formal run. Do not delete inherited or
previous run results. Record the Slurm job ID and final `sacct` output beside
the run.
