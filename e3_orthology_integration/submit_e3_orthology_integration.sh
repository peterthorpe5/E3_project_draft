#!/usr/bin/env bash
# Submit the production integration with explicit scheduler and pipeline options.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SBATCH_SCRIPT="${SCRIPT_DIR}/slurm/e3_orthology_integration.sbatch"
ACCOUNT="barton"
PARTITION="general"
MEMORY="64G"
WALLTIME="24:00:00"
CPUS="4"
JOB_NAME="e3_orthology"
LOG_DIR="${SCRIPT_DIR}/slurm_logs"

usage() {
    cat <<'EOF'
Usage:
  submit_e3_orthology_integration.sh [scheduler options] -- [pipeline options]

Scheduler options:
  --account NAME          Slurm account (default: barton).
  --partition NAME        Slurm partition (default: general).
  --memory SIZE           Requested memory (default: 64G).
  --time HH:MM:SS         Walltime (default: 24:00:00).
  --cpus-per-task INTEGER CPUs for the task (default: 4).
  --job-name NAME         Slurm job name (default: e3_orthology).
  --log-dir PATH          Slurm stdout/stderr directory.
  --help                  Show this help.

Everything after -- is passed unchanged to run_e3_orthology_integration.sh.

Example:
  ./submit_e3_orthology_integration.sh -- \
      --conda-env e3_orthology --threads 4 --resume
EOF
}

while (($#)); do
    case "$1" in
        --account) ACCOUNT="${2:?--account requires a value}"; shift 2 ;;
        --partition) PARTITION="${2:?--partition requires a value}"; shift 2 ;;
        --memory) MEMORY="${2:?--memory requires a value}"; shift 2 ;;
        --time) WALLTIME="${2:?--time requires a value}"; shift 2 ;;
        --cpus-per-task) CPUS="${2:?--cpus-per-task requires a value}"; shift 2 ;;
        --job-name) JOB_NAME="${2:?--job-name requires a value}"; shift 2 ;;
        --log-dir) LOG_DIR="${2:?--log-dir requires a value}"; shift 2 ;;
        --help) usage; exit 0 ;;
        --) shift; break ;;
        *) printf 'ERROR: unknown scheduler option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ "${CPUS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --cpus-per-task must be a positive integer.\n' >&2
    exit 2
}
command -v sbatch >/dev/null 2>&1 || { printf 'ERROR: sbatch is unavailable.\n' >&2; exit 2; }
[[ -x "${SBATCH_SCRIPT}" ]] || { printf 'ERROR: missing %s\n' "${SBATCH_SCRIPT}" >&2; exit 2; }
mkdir -p -- "${LOG_DIR}"

sbatch \
    --account="${ACCOUNT}" \
    --partition="${PARTITION}" \
    --mem="${MEMORY}" \
    --time="${WALLTIME}" \
    --cpus-per-task="${CPUS}" \
    --job-name="${JOB_NAME}" \
    --output="${LOG_DIR}/%x_%j.out" \
    --error="${LOG_DIR}/%x_%j.err" \
    "${SBATCH_SCRIPT}" "$@"
