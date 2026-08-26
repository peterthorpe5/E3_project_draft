#!/bin/bash
## 6. launch the Python application


conda activate e3_python_app

LOCAL_REPO="/Users/PThorpe001/github_repos/E3_project_draft"

LOCAL_RELEASE="/Volumes/Seagate Portable Drive/2026_E3_protac/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805_app_release"
RESOURCE_DB="${LOCAL_RELEASE}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
POCKET_REVIEW="${LOCAL_RELEASE}/pocket_review_top200_v0_3_1"
LOCAL_REPO="/Users/PThorpe001/github_repos/E3_project_draft"


cd "${LOCAL_REPO}/e3_python_app"


LOCAL_PARENT_ROOT="/Users/PThorpe001/e3_app_cache/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"

LOCAL_EXTENSION_ROOT="/Users/PThorpe001/e3_app_cache/grant_human_plant_structural_top200_v0_16_0_20260826"

LOCAL_DB="${LOCAL_PARENT_ROOT}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"

LOCAL_PLANT_REVIEW="${LOCAL_EXTENSION_ROOT}/plant_pocket_review"

LOCAL_COMBINED_REVIEW="${LOCAL_EXTENSION_ROOT}/pocket_review"


./run_e3_python_app.sh \
  --resource-duckdb "${LOCAL_DB}" \
  --pocket-review-dir "${LOCAL_PLANT_REVIEW}" \
  --human-plant-review-dir "${LOCAL_COMBINED_REVIEW}" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501 \
  --validate-only


${LOCAL_REPO}/e3_python_app/run_e3_python_app.sh \
  --resource-duckdb "${RESOURCE_DB}" \
  --pocket-review-dir "${POCKET_REVIEW}" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501




# SAMBA method

conda activate e3_python_app

LOCAL_RELEASE="/Volumes/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"
RESOURCE_DB="${LOCAL_RELEASE}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
POCKET_REVIEW="${LOCAL_RELEASE}/pocket_review_top200_v0_3_1"
LOCAL_REPO="/Users/PThorpe001/github_repos/E3_project_draft"


cd "${LOCAL_REPO}/e3_python_app"


${LOCAL_REPO}/e3_python_app/run_e3_python_app.sh \
  --resource-duckdb "${RESOURCE_DB}" \
  --pocket-review-dir "${POCKET_REVIEW}" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501


ssh-keygen -R login.compute.dundee.ac.uk


REMOTE_RELEASE="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"

LOCAL_CACHE="${HOME}/e3_app_cache/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"

mkdir -p \
  "${LOCAL_CACHE}/10_integrated_resource/duckdb" \
  "${LOCAL_CACHE}/pocket_review_top200_v0_3_1"

rsync -avh --partial --progress \
  "pthorpe001@login.compute.dundee.ac.uk:${REMOTE_RELEASE}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb" \
  "${LOCAL_CACHE}/10_integrated_resource/duckdb/"

rsync -avh --partial --progress \
  "pthorpe001@login.compute.dundee.ac.uk:${REMOTE_RELEASE}/pocket_review_top200_v0_3_1/" \
  "${LOCAL_CACHE}/pocket_review_top200_v0_3_1/"

LOCAL_RELEASE="${HOME}/e3_app_cache/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"
RESOURCE_DB="${LOCAL_RELEASE}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
POCKET_REVIEW="${LOCAL_RELEASE}/pocket_review_top200_v0_3_1"


${LOCAL_REPO}/e3_python_app/run_e3_python_app.sh \
  --resource-duckdb "${RESOURCE_DB}" \
  --pocket-review-dir "${POCKET_REVIEW}" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501