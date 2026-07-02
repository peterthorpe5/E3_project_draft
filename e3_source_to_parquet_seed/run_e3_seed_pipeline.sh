#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/E3_PROTAC_curated_working_copy" >&2
  exit 1
fi

PROJECT_ROOT="$1"
RAW_ROOT="${PROJECT_ROOT}/raw_inherited_selected"
DERIVED_DIR="${PROJECT_ROOT}/derived"
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "${DERIVED_DIR}" "${DERIVED_DIR}/duckdb" "${DERIVED_DIR}/qc"

python "${SCRIPT_ROOT}/scripts/e3_build_manifest.py" \
  --raw-root "${RAW_ROOT}" \
  --out-dir "${DERIVED_DIR}/qc"

python "${SCRIPT_ROOT}/scripts/e3_convert_seed_sources.py" \
  --raw-root "${RAW_ROOT}" \
  --out-dir "${DERIVED_DIR}" \
  --copy-existing-parquet

python "${SCRIPT_ROOT}/scripts/e3_clean_macos_sidecars.py" \
  --root "${DERIVED_DIR}" \
  --out-tsv "${DERIVED_DIR}/qc/macos_sidecar_report.tsv"

python "${SCRIPT_ROOT}/scripts/e3_create_duckdb_views.py" \
  --derived-dir "${DERIVED_DIR}" \
  --duckdb-path "${DERIVED_DIR}/duckdb/e3_protac_resource.duckdb"

echo "Done. Derived outputs are in: ${DERIVED_DIR}"
