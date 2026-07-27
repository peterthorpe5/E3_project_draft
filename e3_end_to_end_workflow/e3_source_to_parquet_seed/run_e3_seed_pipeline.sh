#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 PROJECT_ROOT [EXPRESSION_DUCKDB] [DERIVED_DIR]" >&2
  echo "Example: $0 /Volumes/ExtremeSSD/E3_PROTAC_curated_working_copy_20260702_105742 /path/to/e3_expression.duckdb /path/to/output_derived" >&2
  exit 1
fi

PROJECT_ROOT="$1"
EXPRESSION_DUCKDB="${2:-}"
RAW_ROOT="${PROJECT_ROOT}/raw_inherited_selected"
DERIVED_DIR="${3:-${PROJECT_ROOT}/derived}"
DUCKDB_PATH="${DERIVED_DIR}/duckdb/e3_protac_resource.duckdb"

mkdir -p "${DERIVED_DIR}/logs" "${DERIVED_DIR}/qc" "${DERIVED_DIR}/duckdb"

echo "[1/6] Building source manifest"
python scripts/e3_build_manifest.py \
  --raw-root "${RAW_ROOT}" \
  --out-dir "${DERIVED_DIR}/qc"

echo "[2/6] Converting selected source files to source-preserving Parquet"
python scripts/e3_convert_seed_sources.py \
  --raw-root "${RAW_ROOT}" \
  --out-dir "${DERIVED_DIR}" \
  --copy-existing-parquet

echo "[3/6] Removing/reporting macOS sidecar files from derived outputs"
python scripts/e3_clean_macos_sidecars.py \
  --root "${DERIVED_DIR}" \
  --out-tsv "${DERIVED_DIR}/qc/macos_sidecar_deleted.tsv" \
  --delete

echo "[4/6] Creating DuckDB views over source-preserving Parquet"
python scripts/e3_create_duckdb_views.py \
  --derived-dir "${DERIVED_DIR}" \
  --duckdb-path "${DUCKDB_PATH}"

echo "[5/6] Creating curated E3 interrogation views and debug reports"
if [[ -n "${EXPRESSION_DUCKDB}" ]]; then
  python scripts/e3_build_curated_resource.py \
    --raw-root "${RAW_ROOT}" \
    --derived-dir "${DERIVED_DIR}" \
    --duckdb-path "${DUCKDB_PATH}" \
    --expression-duckdb "${EXPRESSION_DUCKDB}"
else
  python scripts/e3_build_curated_resource.py \
    --raw-root "${RAW_ROOT}" \
    --derived-dir "${DERIVED_DIR}" \
    --duckdb-path "${DUCKDB_PATH}"
fi


echo "[6/6] Writing human-readable files-used report"
python scripts/e3_write_files_used_report.py \
  --derived-dir "${DERIVED_DIR}" \
  --output "${DERIVED_DIR}/docs/FILES_USED_AND_CURATED_VIEWS.md"

echo "Done. Derived output directory: ${DERIVED_DIR}"
echo "Done. Main DuckDB: ${DUCKDB_PATH}"
echo "Key debug report: ${DERIVED_DIR}/qc/curated_resource_debug.md"
echo "Expression/RNAseq status: ${DERIVED_DIR}/qc/expression_resource_status.tsv"
