# Top-200 portable visualisation release runbook

This runbook creates a self-contained laptop release from the completed
top-200 workflow. Run the cluster sections from a University of Dundee Slurm
login node. Run the transfer and launch sections from Terminal on the Mac.

The visualisation bundle does not change or rebuild the authoritative
integrated DuckDB. It packages the additional model coordinates, pocket
annotations, MAFFT alignments and member identifiers needed by the two Shiny
visual-review tabs.

## 1. Submit the top-200 pocket-review build on the cluster

Start from the current `E3_project_draft` Git clone:

```bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
RUN_ROOT="/home/pthorpe001/data/2026_E3_protac/analysis/e3_end_to_end_runs/grant_aligned_structural_sensitivity_top200_v0_11_0_20260730"
POCKET_REVIEW="${RUN_ROOT}/pocket_review_top200_v0_3_1"

test -d "${REPO_ROOT}/e3_structural_alignment"
test -d "${RUN_ROOT}"

"${REPO_ROOT}/e3_structural_alignment/scripts/submit_e3_pocket_review_slurm.sh" \
    --run-root "${RUN_ROOT}" \
    --output-dir "${POCKET_REVIEW}" \
    --account barton \
    --partition barton \
    --walltime 04:00:00 \
    --memory 16G \
    --cpus 4 \
    --conda-environment e3_structural_alignment \
    --review-limit 200 \
    --member-pocket-top-k 5 \
    --resume
```

The submitter prints the Slurm job ID and log path. Monitor them with:

```bash
squeue --me --name e3_pocket_review
```

After the job leaves the queue, inspect the log printed by the submitter. The
last line should report a completed pocket-review build.

## 2. Validate and assemble the portable release on the cluster

Run this only after the Slurm job has completed successfully:

```bash
set -euo pipefail

RUN_ROOT="/home/pthorpe001/data/2026_E3_protac/analysis/e3_end_to_end_runs/grant_aligned_structural_sensitivity_top200_v0_11_0_20260730"
POCKET_REVIEW="${RUN_ROOT}/pocket_review_top200_v0_3_1"
PORTABLE_ROOT="${RUN_ROOT}/portable_visualisation_release_top200_20260803"

RESOURCE_DB="${RUN_ROOT}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
MASTER_PARQUET="${RUN_ROOT}/10_integrated_resource/tables/e3_candidate_master_results.parquet"
REVIEW_INDEX="${POCKET_REVIEW}/tables/review_report_index.tsv"
REVIEW_MANIFEST="${POCKET_REVIEW}/provenance/run_manifest.json"

test -s "${RESOURCE_DB}"
test -s "${MASTER_PARQUET}"
test -s "${REVIEW_INDEX}"
test -s "${REVIEW_MANIFEST}"

REVIEW_GROUP_COUNT="$(awk 'NR > 1 {count++} END {print count + 0}' "${REVIEW_INDEX}")"
if [[ "${REVIEW_GROUP_COUNT}" -ne 200 ]]; then
    printf 'ERROR: expected 200 review groups; found %s\n' \
        "${REVIEW_GROUP_COUNT}" >&2
    exit 1
fi

if [[ -e "${PORTABLE_ROOT}" ]]; then
    printf 'ERROR: portable release already exists: %s\n' \
        "${PORTABLE_ROOT}" >&2
    exit 1
fi

mkdir -p "${PORTABLE_ROOT}"
cp -p "${RESOURCE_DB}" "${PORTABLE_ROOT}/"
cp -p "${MASTER_PARQUET}" "${PORTABLE_ROOT}/"
rsync -a "${POCKET_REVIEW}/" "${PORTABLE_ROOT}/pocket_review/"
rsync -a "${RUN_ROOT}/11_app_ready/" "${PORTABLE_ROOT}/11_app_ready/"

(
    cd "${PORTABLE_ROOT}"
    find . -type f ! -name SHA256SUMS.txt -print0 |
        LC_ALL=C sort -z |
        xargs -0 sha256sum
) > "${PORTABLE_ROOT}/SHA256SUMS.txt"

test "$(find "${PORTABLE_ROOT}/pocket_review/groups" \
    -maxdepth 1 -type f -name '*.html' | wc -l)" -eq 200

du -sh "${PORTABLE_ROOT}"
find "${PORTABLE_ROOT}" -maxdepth 2 -type f -printf '%P\t%k KiB\n' |
    LC_ALL=C sort
```

The command deliberately stops if the release directory already exists. This
prevents a new release from being silently mixed with an older one.

## 3. Copy the release to the external drive from the Mac

```bash
set -euo pipefail

PORTABLE_DEST="/Volumes/One Touch/2026_E3_protac/portable_visualisation_release_top200_20260803"

mkdir -p "$(dirname "${PORTABLE_DEST}")"

rsync -avhP --stats \
    pthorpe001@login.compute.dundee.ac.uk:/home/pthorpe001/data/2026_E3_protac/analysis/e3_end_to_end_runs/grant_aligned_structural_sensitivity_top200_v0_11_0_20260730/portable_visualisation_release_top200_20260803/ \
    "${PORTABLE_DEST}/"
```

Verify every copied file:

```bash
cd "/Volumes/One Touch/2026_E3_protac/portable_visualisation_release_top200_20260803"
shasum -a 256 -c SHA256SUMS.txt
```

Every line should end in `OK`.

## 4. Launch Shiny v0.6.0 from the Mac

```bash
set -euo pipefail

PORTABLE_ROOT="/Volumes/One Touch/2026_E3_protac/portable_visualisation_release_top200_20260803"
RESOURCE_DB="${PORTABLE_ROOT}/e3_integrated_resource.duckdb"
POCKET_REVIEW="${PORTABLE_ROOT}/pocket_review"

test -r "${RESOURCE_DB}"
test -r "${POCKET_REVIEW}/index.html"

conda activate e3_shiny_app
cd /path/to/E3_shiny_app

./run_app.sh \
    --resource_duckdb_path "${RESOURCE_DB}" \
    --pocket_review_dir "${POCKET_REVIEW}" \
    --expression_duckdb_path "" \
    --max_table_rows 1000 \
    --host 127.0.0.1 \
    --port 3838
```

Open <http://127.0.0.1:3838>. The new tabs are **3D structures & pockets** and
**Pocket-aligned sequences**. Keep the external drive connected while the app
is running.

## 5. Interpretation boundary

The embedded structure view is an offline, rotatable C-alpha trace with mapped
pocket residues. It is appropriate for checking relative pocket location and
member coverage, but it is not an atomistic molecular surface, docking result
or binding prediction. The strict rank-one and exploratory rank-two-to-five
pockets remain visibly distinct.
