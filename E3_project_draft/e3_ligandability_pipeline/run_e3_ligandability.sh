#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  ./run_e3_ligandability.sh ACCESSIONS OUTPUT_DIR [CONFIG_YAML] [CONDA_ENV]

Arguments:
  ACCESSIONS   Plain-text, TSV or CSV accession input.
  OUTPUT_DIR   New or resumable output directory.
  CONFIG_YAML  Optional YAML configuration. Defaults to
               config/config.cluster.example.yaml.
  CONDA_ENV    Optional Conda environment. Defaults to e3_ligandability.
USAGE
}

if [[ $# -lt 2 || $# -gt 4 ]]; then
    usage >&2
    exit 64
fi

INPUT_PATH="$1"
OUTPUT_DIR="$2"
CONFIG_PATH="${3:-config/config.cluster.example.yaml}"
CONDA_ENV="${4:-e3_ligandability}"

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
)"

if [[ ! -f "${INPUT_PATH}" ]]; then
    echo "ERROR: Accession input not found: ${INPUT_PATH}" >&2
    exit 66
fi
INPUT_PATH="$(
    cd -- "$(dirname -- "${INPUT_PATH}")" >/dev/null 2>&1
    printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${INPUT_PATH}")"
)"

if [[ ! -f "${CONFIG_PATH}" ]]; then
    if [[ -f "${SCRIPT_DIR}/${CONFIG_PATH}" ]]; then
        CONFIG_PATH="${SCRIPT_DIR}/${CONFIG_PATH}"
    else
        echo "ERROR: Configuration not found: ${CONFIG_PATH}" >&2
        exit 66
    fi
fi
CONFIG_PATH="$(
    cd -- "$(dirname -- "${CONFIG_PATH}")" >/dev/null 2>&1
    printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${CONFIG_PATH}")"
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

mkdir -p "${OUTPUT_DIR}/logs" "${OUTPUT_DIR}/provenance"
WRAPPER_LOG="${OUTPUT_DIR}/logs/run_e3_ligandability_wrapper.log"
CONDA_EXPLICIT="${OUTPUT_DIR}/provenance/conda_explicit_spec.txt"
CONDA_EXPORT="${OUTPUT_DIR}/provenance/conda_environment_no_builds.yaml"

"${CONDA_EXE}" list -n "${CONDA_ENV}" --explicit > "${CONDA_EXPLICIT}"
"${CONDA_EXE}" env export -n "${CONDA_ENV}" --no-builds > "${CONDA_EXPORT}"

{
    echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Host: $(hostname -f 2>/dev/null || hostname)"
    echo "Input: ${INPUT_PATH}"
    echo "Output: ${OUTPUT_DIR}"
    echo "Config: ${CONFIG_PATH}"
    echo "Conda executable: ${CONDA_EXE}"
    echo "Conda environment: ${CONDA_ENV}"
    echo "Conda explicit specification: ${CONDA_EXPLICIT}"
    echo "Conda environment export: ${CONDA_EXPORT}"
    "${CONDA_EXE}" run -n "${CONDA_ENV}" python --version
    "${CONDA_EXE}" run -n "${CONDA_ENV}" python -c \
        'import e3ligandability; print(e3ligandability.__version__)'
} | tee "${WRAPPER_LOG}"

cd "${SCRIPT_DIR}"

set +e
"${CONDA_EXE}" run --no-capture-output -n "${CONDA_ENV}" \
    python -m e3ligandability.cli run \
    --input "${INPUT_PATH}" \
    --output-dir "${OUTPUT_DIR}" \
    --config "${CONFIG_PATH}" \
    --git-repository "${SCRIPT_DIR}" \
    2>&1 | tee -a "${WRAPPER_LOG}"
PIPELINE_STATUS=${PIPESTATUS[0]}
set -e

echo "Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${WRAPPER_LOG}"
echo "Exit status: ${PIPELINE_STATUS}" | tee -a "${WRAPPER_LOG}"
exit "${PIPELINE_STATUS}"
