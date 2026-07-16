#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage:
  run_e3_candidate_evidence.sh DISCOVERY_DUCKDB OUTPUT_DIR [options]

Options:
  --conda-env NAME       Conda environment (default: e3_discovery)
  --overwrite            Replace existing formal outputs
  --skip-source-sha256   Skip source DuckDB SHA-256 calculation
  --verbose              Print DEBUG messages
  -h, --help             Show this help text
EOF
}

if [[ $# -lt 2 ]]; then
    usage
    exit 2
fi

DISCOVERY_DUCKDB="$1"
OUTPUT_DIR="$2"
shift 2

CONDA_ENV="e3_discovery"
OVERWRITE="false"
SKIP_SOURCE_SHA256="false"
VERBOSE="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --conda-env)
            [[ $# -ge 2 ]] || {
                echo "ERROR: --conda-env requires a value." >&2
                exit 2
            }
            CONDA_ENV="$2"
            shift 2
            ;;
        --overwrite)
            OVERWRITE="true"
            shift
            ;;
        --skip-source-sha256)
            SKIP_SOURCE_SHA256="true"
            shift
            ;;
        --verbose)
            VERBOSE="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            usage
            exit 2
            ;;
    esac
done

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
)"
PYTHON_SCRIPT="${SCRIPT_DIR}/scripts/e3_build_candidate_evidence.py"

[[ -f "${DISCOVERY_DUCKDB}" ]] || {
    echo "ERROR: Missing discovery DuckDB: ${DISCOVERY_DUCKDB}" >&2
    exit 1
}
[[ -f "${PYTHON_SCRIPT}" ]] || {
    echo "ERROR: Missing Python build script: ${PYTHON_SCRIPT}" >&2
    exit 1
}

mkdir -p "${OUTPUT_DIR}/logs"
WRAPPER_LOG="${OUTPUT_DIR}/logs/run_e3_candidate_evidence_wrapper.log"
exec > >(tee -a "${WRAPPER_LOG}") 2>&1

echo "Started candidate evidence wrapper: $(date --iso-8601=seconds 2>/dev/null || date)"
echo "Host: $(hostname)"
echo "Repository: ${SCRIPT_DIR}"
echo "Source DuckDB: ${DISCOVERY_DUCKDB}"
echo "Output directory: ${OUTPUT_DIR}"
echo "Conda environment: ${CONDA_ENV}"
echo "Wrapper log: ${WRAPPER_LOG}"

CONDA_PATH="${CONDA_EXE:-$(command -v conda || true)}"
[[ -n "${CONDA_PATH}" ]] || {
    echo "ERROR: conda was not found." >&2
    exit 1
}
CONDA_BASE="$("${CONDA_PATH}" info --base)"
CONDA_SH="${CONDA_BASE}/etc/profile.d/conda.sh"
[[ -f "${CONDA_SH}" ]] || {
    echo "ERROR: Missing conda.sh: ${CONDA_SH}" >&2
    exit 1
}

# shellcheck disable=SC1090
source "${CONDA_SH}"
conda activate "${CONDA_ENV}"
PYTHON_EXE="$(command -v python)"
echo "Resolved Python: ${PYTHON_EXE}"
"${PYTHON_EXE}" --version

"${PYTHON_EXE}" - <<'PY'
"""Fail early when required dependencies are unavailable."""

import duckdb
import pyarrow

print(f"DuckDB version: {duckdb.__version__}")
print(f"PyArrow version: {pyarrow.__version__}")
PY

COMMAND=(
    "${PYTHON_EXE}"
    "${PYTHON_SCRIPT}"
    --discovery-duckdb "${DISCOVERY_DUCKDB}"
    --output-dir "${OUTPUT_DIR}"
)
[[ "${OVERWRITE}" == "true" ]] && COMMAND+=(--overwrite)
[[ "${SKIP_SOURCE_SHA256}" == "true" ]] && COMMAND+=(--skip-source-sha256)
[[ "${VERBOSE}" == "true" ]] && COMMAND+=(--verbose)

printf 'Command:'
printf ' %q' "${COMMAND[@]}"
printf '\n'
"${COMMAND[@]}"

echo "Candidate TSV: ${OUTPUT_DIR}/candidate_evidence/e3_cluster_candidate_evidence.tsv"
echo "Candidate Parquet: ${OUTPUT_DIR}/candidate_evidence/e3_cluster_candidate_evidence.parquet"
echo "Validation: ${OUTPUT_DIR}/qc/e3_cluster_candidate_evidence_validation.tsv"
echo "DuckDB: ${OUTPUT_DIR}/duckdb/e3_candidate_evidence.duckdb"
echo "Manifest: ${OUTPUT_DIR}/provenance/e3_cluster_candidate_evidence_manifest.json"
echo "Finished candidate evidence wrapper: $(date --iso-8601=seconds 2>/dev/null || date)"
