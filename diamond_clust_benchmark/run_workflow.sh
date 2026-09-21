#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH=""
CORES=""
DRY_RUN=0

usage() {
    printf '%s\n' \
        'Usage: ./run_workflow.sh --config PATH [--cores N] [--dry-run]' \
        '' \
        'Runs benchmark cases sequentially so methods do not compete for CPUs,' \
        'memory, scratch space or filesystem bandwidth.'
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 2
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="${2:?}"; shift 2 ;;
        --cores) CORES="${2:?}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ -n "${CONFIG_PATH}" ]] || die '--config is required'
[[ -f "${CONFIG_PATH}" ]] || die "Configuration does not exist: ${CONFIG_PATH}"
command -v realpath >/dev/null 2>&1 || die 'realpath is required'
command -v snakemake >/dev/null 2>&1 || die 'snakemake is not available'

CONFIG_PATH="$(realpath "${CONFIG_PATH}")"
if [[ -z "${CORES}" ]]; then
    CORES="${SLURM_CPUS_PER_TASK:-1}"
fi
[[ "${CORES}" =~ ^[1-9][0-9]*$ ]] || die '--cores must be a positive integer'

export DIAMOND_BENCHMARK_CONFIG="${CONFIG_PATH}"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

COMMAND=(
    snakemake
    --snakefile "${SCRIPT_DIR}/Snakefile"
    --cores "${CORES}"
    --resources benchmark_slot=1
    --rerun-incomplete
    --printshellcmds
    --show-failed-logs
    --latency-wait 120
)
if [[ "${DRY_RUN}" -eq 1 ]]; then
    COMMAND+=(--dry-run)
fi
"${COMMAND[@]}"
