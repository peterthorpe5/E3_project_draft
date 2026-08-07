## 5. Launch R Shiny with the corrected release

LOCAL_RELEASE="/Volumes/One Touch/2026_E3_protac/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805_app_release"
RESOURCE_DB="${LOCAL_RELEASE}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
POCKET_REVIEW="${LOCAL_RELEASE}/pocket_review_top200_v0_3_1"
LOCAL_REPO="/Users/PThorpe001/github_repos/E3_project_draft"

conda activate e3_shiny_app
cd "${LOCAL_REPO}/E3_shiny_app"

./run_app.sh \
  --resource_duckdb_path "${RESOURCE_DB}" \
  --pocket_review_dir "${POCKET_REVIEW}" \
  --expression_duckdb_path "" \
  --max_table_rows 1000 \
  --host 127.0.0.1 \
  --port 3838

  
Open <http://127.0.0.1:3838>.

## 6. launch the Python application


conda activate e3_python_app

LOCAL_REPO="/Users/PThorpe001/github_repos/E3_project_draft"

LOCAL_RELEASE="/Volumes/One Touch/2026_E3_protac/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805_app_release"
RESOURCE_DB="${LOCAL_RELEASE}/10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
POCKET_REVIEW="${LOCAL_RELEASE}/pocket_review_top200_v0_3_1"
LOCAL_REPO="/Users/PThorpe001/github_repos/E3_project_draft"


cd "${LOCAL_REPO}/e3_python_app"


./run_e3_python_app.sh \
  --resource-duckdb "${RESOURCE_DB}" \
  --pocket-review-dir "${POCKET_REVIEW}" \
  --max-rows 1000 \
  --host 127.0.0.1 \
  --port 8501


