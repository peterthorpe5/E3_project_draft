#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH=""
RUN_ROOT=""
OUTPUT_DIRECTORY=""
SENTINEL_IDS_TSV=""
ACCOUNT="barton"
PARTITION="barton"
CPUS=2
MEMORY="256G"
DUCKDB_MEMORY_LIMIT="200GB"
TEMPORARY_DIRECTORY="auto"
WALLTIME="4-00:00:00"
CONDA_ENV="e3_discovery"
JOB_NAME="diamond_all_pairs"
LOG_DIRECTORY="${PACKAGE_ROOT}/slurm_logs"
RESUME="false"

usage() {
    printf '%s\n' \
        'Usage: ./scripts/submit_all_against_all_slurm.sh [required options] [options]' \
        '' \
        'Required:' \
        '  --config PATH           Completed benchmark configuration.' \
        '  --run-root PATH         Existing benchmark result root.' \
        '  --output-directory PATH New or resumable analysis directory.' \
        '' \
        'Options:' \
        '  --sentinel-ids-tsv PATH Override the sentinel TSV in the config.' \
        '  --account NAME          Slurm account. Default: barton.' \
        '  --partition NAME        Slurm partition. Default: barton.' \
        '  --cpus N                DuckDB threads. Default: 2.' \
        '  --memory VALUE          Slurm memory. Default: 256G.' \
        '  --duckdb-memory VALUE   DuckDB limit. Default: 200GB.' \
        '  --temporary-directory PATH|auto  DuckDB database and spill space.' \
        '  --time VALUE            Slurm time. Default: 4-00:00:00.' \
        '  --conda-env NAME        Conda environment. Default: e3_discovery.' \
        '  --job-name NAME         Slurm job name.' \
        '  --log-directory PATH    Persistent Slurm log directory.' \
        '  --resume                Reuse valid completed-pair checkpoints.'
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 2
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="${2:?}"; shift 2 ;;
        --run-root) RUN_ROOT="${2:?}"; shift 2 ;;
        --output-directory) OUTPUT_DIRECTORY="${2:?}"; shift 2 ;;
        --sentinel-ids-tsv) SENTINEL_IDS_TSV="${2:?}"; shift 2 ;;
        --account) ACCOUNT="${2:?}"; shift 2 ;;
        --partition) PARTITION="${2:?}"; shift 2 ;;
        --cpus) CPUS="${2:?}"; shift 2 ;;
        --memory) MEMORY="${2:?}"; shift 2 ;;
        --duckdb-memory) DUCKDB_MEMORY_LIMIT="${2:?}"; shift 2 ;;
        --temporary-directory) TEMPORARY_DIRECTORY="${2:?}"; shift 2 ;;
        --time) WALLTIME="${2:?}"; shift 2 ;;
        --conda-env) CONDA_ENV="${2:?}"; shift 2 ;;
        --job-name) JOB_NAME="${2:?}"; shift 2 ;;
        --log-directory) LOG_DIRECTORY="${2:?}"; shift 2 ;;
        --resume) RESUME="true"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ -n "${CONFIG_PATH}" ]] || die '--config is required'
[[ -f "${CONFIG_PATH}" ]] || die "Configuration does not exist: ${CONFIG_PATH}"
[[ -n "${RUN_ROOT}" ]] || die '--run-root is required'
[[ -d "${RUN_ROOT}" ]] || die "Run root does not exist: ${RUN_ROOT}"
[[ -n "${OUTPUT_DIRECTORY}" ]] || die '--output-directory is required'
if [[ -n "${SENTINEL_IDS_TSV}" && ! -f "${SENTINEL_IDS_TSV}" ]]; then
    die "Sentinel TSV does not exist: ${SENTINEL_IDS_TSV}"
fi
[[ "${CPUS}" =~ ^[1-9][0-9]*$ ]] || die '--cpus must be a positive integer'
[[ "${DUCKDB_MEMORY_LIMIT}" =~ ^[0-9]+([.][0-9]+)?(KB|MB|GB|TB)$ ]] || \
    die '--duckdb-memory must resemble 200GB'
command -v sbatch >/dev/null 2>&1 || die 'sbatch is not available'
command -v conda >/dev/null 2>&1 || die 'conda is not available'
command -v realpath >/dev/null 2>&1 || die 'realpath is required'

CONFIG_PATH="$(realpath "${CONFIG_PATH}")"
RUN_ROOT="$(realpath "${RUN_ROOT}")"
PACKAGE_ROOT="$(realpath "${PACKAGE_ROOT}")"
mkdir -p "${OUTPUT_DIRECTORY}" "${LOG_DIRECTORY}"
OUTPUT_DIRECTORY="$(realpath "${OUTPUT_DIRECTORY}")"
LOG_DIRECTORY="$(realpath "${LOG_DIRECTORY}")"
if [[ -n "${SENTINEL_IDS_TSV}" ]]; then
    SENTINEL_IDS_TSV="$(realpath "${SENTINEL_IDS_TSV}")"
fi

EXPORTS="ALL"
EXPORTS+=",DIAMOND_ALL_PAIRS_ROOT=${PACKAGE_ROOT}"
EXPORTS+=",DIAMOND_ALL_PAIRS_CONFIG=${CONFIG_PATH}"
EXPORTS+=",DIAMOND_ALL_PAIRS_RUN_ROOT=${RUN_ROOT}"
EXPORTS+=",DIAMOND_ALL_PAIRS_OUTPUT=${OUTPUT_DIRECTORY}"
EXPORTS+=",DIAMOND_ALL_PAIRS_ENV=${CONDA_ENV}"
EXPORTS+=",DIAMOND_ALL_PAIRS_MEMORY_LIMIT=${DUCKDB_MEMORY_LIMIT}"
EXPORTS+=",DIAMOND_ALL_PAIRS_TEMPORARY=${TEMPORARY_DIRECTORY}"
EXPORTS+=",DIAMOND_ALL_PAIRS_RESUME=${RESUME}"
if [[ -n "${SENTINEL_IDS_TSV}" ]]; then
    EXPORTS+=",DIAMOND_ALL_PAIRS_SENTINELS=${SENTINEL_IDS_TSV}"
fi

JOB_ID="$(
    sbatch \
        --parsable \
        --job-name="${JOB_NAME}" \
        --account="${ACCOUNT}" \
        --partition="${PARTITION}" \
        --nodes=1 \
        --ntasks=1 \
        --cpus-per-task="${CPUS}" \
        --mem="${MEMORY}" \
        --time="${WALLTIME}" \
        --output="${LOG_DIRECTORY}/slurm-%j.out" \
        --error="${LOG_DIRECTORY}/slurm-%j.err" \
        --export="${EXPORTS}" \
        "${PACKAGE_ROOT}/scripts/slurm_all_against_all.sh"
)"
JOB_ID="${JOB_ID%%;*}"

printf 'Submitted all-against-all job: %s\n' "${JOB_ID}"
printf 'Output log: %s\n' "${LOG_DIRECTORY}/slurm-${JOB_ID}.out"
printf 'Error log: %s\n' "${LOG_DIRECTORY}/slurm-${JOB_ID}.err"
printf 'Analysis directory: %s\n' "${OUTPUT_DIRECTORY}"
