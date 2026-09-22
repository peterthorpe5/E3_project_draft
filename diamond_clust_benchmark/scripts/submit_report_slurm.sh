#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH=""
RUN_ROOT=""
ACCOUNT="barton"
PARTITION="barton"
CPUS=2
MEMORY="256G"
WALLTIME="2-00:00:00"
CONDA_ENV="e3_discovery"
JOB_NAME="diamond_clust_report"
LOG_DIRECTORY="${PACKAGE_ROOT}/slurm_logs"

usage() {
    printf '%s\n' \
        'Usage: ./scripts/submit_report_slurm.sh --config PATH --run-root PATH [options]' \
        '' \
        'Submits only final quality comparison and reporting; DIAMOND cannot run.' \
        '' \
        'Options:' \
        '  --account NAME       Slurm account. Default: barton.' \
        '  --partition NAME     Slurm partition. Default: barton.' \
        '  --cpus N             CPUs per task. Default: 2.' \
        '  --memory VALUE       Slurm memory. Default: 256G.' \
        '  --time VALUE         Slurm time. Default: 2-00:00:00.' \
        '  --conda-env NAME     Controller environment. Default: e3_discovery.' \
        '  --job-name NAME      Slurm job name.' \
        '  --log-directory PATH Persistent Slurm log directory.'
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 2
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="${2:?}"; shift 2 ;;
        --run-root) RUN_ROOT="${2:?}"; shift 2 ;;
        --account) ACCOUNT="${2:?}"; shift 2 ;;
        --partition) PARTITION="${2:?}"; shift 2 ;;
        --cpus) CPUS="${2:?}"; shift 2 ;;
        --memory) MEMORY="${2:?}"; shift 2 ;;
        --time) WALLTIME="${2:?}"; shift 2 ;;
        --conda-env) CONDA_ENV="${2:?}"; shift 2 ;;
        --job-name) JOB_NAME="${2:?}"; shift 2 ;;
        --log-directory) LOG_DIRECTORY="${2:?}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ -n "${CONFIG_PATH}" ]] || die '--config is required'
[[ -f "${CONFIG_PATH}" ]] || die "Configuration does not exist: ${CONFIG_PATH}"
[[ -n "${RUN_ROOT}" ]] || die '--run-root is required'
[[ -d "${RUN_ROOT}" ]] || die "Run root does not exist: ${RUN_ROOT}"
[[ "${CPUS}" =~ ^[1-9][0-9]*$ ]] || die '--cpus must be a positive integer'
command -v sbatch >/dev/null 2>&1 || die 'sbatch is not available'
command -v conda >/dev/null 2>&1 || die 'conda is not available'
command -v realpath >/dev/null 2>&1 || die 'realpath is required'

CONFIG_PATH="$(realpath "${CONFIG_PATH}")"
RUN_ROOT="$(realpath "${RUN_ROOT}")"
PACKAGE_ROOT="$(realpath "${PACKAGE_ROOT}")"
mkdir -p "${LOG_DIRECTORY}"
LOG_DIRECTORY="$(realpath "${LOG_DIRECTORY}")"

conda run --no-capture-output --name "${CONDA_ENV}" \
    python -m diamond_clust_benchmark.cli validate-config \
    --config "${CONFIG_PATH}" \
    --output "${LOG_DIRECTORY}/validated_report_config.json"

EXPORTS="ALL"
EXPORTS+=",DIAMOND_BENCHMARK_ROOT=${PACKAGE_ROOT}"
EXPORTS+=",DIAMOND_BENCHMARK_CONFIG=${CONFIG_PATH}"
EXPORTS+=",DIAMOND_BENCHMARK_RUN_ROOT=${RUN_ROOT}"
EXPORTS+=",DIAMOND_BENCHMARK_ENV=${CONDA_ENV}"

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
        "${PACKAGE_ROOT}/scripts/slurm_report.sh"
)"
JOB_ID="${JOB_ID%%;*}"

printf 'Submitted report-only job: %s\n' "${JOB_ID}"
printf 'Output log: %s\n' "${LOG_DIRECTORY}/slurm-${JOB_ID}.out"
printf 'Error log: %s\n' "${LOG_DIRECTORY}/slurm-${JOB_ID}.err"
