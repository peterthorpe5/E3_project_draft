#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  ./run_legacy_regression.sh TESTING_ROOT METADATA_CSV OUTPUT_DIR [CONDA_ENV]

Arguments:
  TESTING_ROOT  Inherited data/testing directory containing model files.
  METADATA_CSV  Inherited AlphaFold metadata CSV.
  OUTPUT_DIR    New regression output directory.
  CONDA_ENV     Optional Conda environment; default e3_ligandability.
USAGE
}

if [[ $# -lt 3 || $# -gt 4 ]]; then
    usage >&2
    exit 64
fi

TESTING_ROOT="$1"
METADATA_CSV="$2"
OUTPUT_DIR="$3"
CONDA_ENV="${4:-e3_ligandability}"

for required_path in "${TESTING_ROOT}" "${METADATA_CSV}"; do
    if [[ ! -e "${required_path}" ]]; then
        echo "ERROR: Required input is missing: ${required_path}" >&2
        exit 66
    fi
done

TESTING_ROOT="$(cd -- "${TESTING_ROOT}" >/dev/null 2>&1 && pwd -P)"
METADATA_CSV="$(
    cd -- "$(dirname -- "${METADATA_CSV}")" >/dev/null 2>&1
    printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${METADATA_CSV}")"
)"
mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR="$(cd -- "${OUTPUT_DIR}" >/dev/null 2>&1 && pwd -P)"

CONDA_EXE="${CONDA_EXE:-$(command -v conda || true)}"
if [[ -z "${CONDA_EXE}" || ! -x "${CONDA_EXE}" ]]; then
    echo "ERROR: Conda executable was not found." >&2
    exit 69
fi
if ! "${CONDA_EXE}" env list | awk '{print $1}' | grep -Fxq "${CONDA_ENV}"; then
    echo "ERROR: Conda environment not found: ${CONDA_ENV}" >&2
    exit 69
fi

exec "${CONDA_EXE}" run --no-capture-output -n "${CONDA_ENV}" \
    python -m e3ligandability.cli validate-legacy \
    --testing-root "${TESTING_ROOT}" \
    --metadata-csv "${METADATA_CSV}" \
    --output-dir "${OUTPUT_DIR}"
