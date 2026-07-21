#!/usr/bin/env bash
# Submit the production integration with explicit scheduler and pipeline options.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SBATCH_SCRIPT="${SCRIPT_DIR}/slurm/e3_orthology_integration.sbatch"
RUNNER="${SCRIPT_DIR}/run_e3_orthology_integration.sh"
ACCOUNT="barton"
PARTITION="general"
MEMORY="64G"
WALLTIME="24:00:00"
CPUS="4"
JOB_NAME="e3_orthology"
LOG_DIR=""

usage() {
    cat <<'EOF'
Usage:
  submit_e3_orthology_integration.sh [scheduler options] -- [pipeline options]

Scheduler options:
  --account NAME          Slurm account (default: barton).
  --partition NAME        Slurm partition (default: general).
  --memory SIZE           Requested memory (default: 64G).
  --time HH:MM:SS         Walltime (default: 24:00:00).
  --cpus-per-task INTEGER CPUs for the task (default: 4; must match --threads).
  --job-name NAME         Slurm job name (default: e3_orthology).
  --log-dir PATH          Slurm stdout/stderr directory (default: RUN_ROOT/slurm_logs).
  --help                  Show this help.

Everything after -- is passed to run_e3_orthology_integration.sh. If pipeline --threads is
omitted, it is set to --cpus-per-task. An explicit --threads value must match the CPU request.

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
declare -a PIPELINE_ARGS=("$@")
PIPELINE_THREADS=""
THREAD_OPTION_COUNT=0
for ((index = 0; index < ${#PIPELINE_ARGS[@]}; index++)); do
    argument="${PIPELINE_ARGS[index]}"
    case "${argument}" in
        --threads)
            ((index + 1 < ${#PIPELINE_ARGS[@]})) || {
                printf 'ERROR: pipeline --threads requires a value.\n' >&2
                exit 2
            }
            PIPELINE_THREADS="${PIPELINE_ARGS[index + 1]}"
            ((THREAD_OPTION_COUNT += 1))
            ((index += 1))
            ;;
        --threads=*)
            PIPELINE_THREADS="${argument#--threads=}"
            ((THREAD_OPTION_COUNT += 1))
            ;;
    esac
done
if ((THREAD_OPTION_COUNT > 1)); then
    printf 'ERROR: pipeline --threads may be supplied only once.\n' >&2
    exit 2
fi
if [[ -z "${PIPELINE_THREADS}" ]]; then
    PIPELINE_THREADS="${CPUS}"
    PIPELINE_ARGS+=(--threads "${PIPELINE_THREADS}")
fi
if [[ ! "${PIPELINE_THREADS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: pipeline --threads must be a positive integer.\n' >&2
    exit 2
fi
if [[ "${PIPELINE_THREADS}" != "${CPUS}" ]]; then
    printf 'ERROR: --cpus-per-task (%s) must equal pipeline --threads (%s).\n' \
        "${CPUS}" "${PIPELINE_THREADS}" >&2
    exit 2
fi
[[ "${WALLTIME}" =~ ^([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])$ ]] || {
    printf 'ERROR: --time must use HH:MM:SS with valid minute and second fields.\n' >&2
    exit 2
}
WALLTIME_HOURS="$((10#${BASH_REMATCH[1]}))"
WALLTIME_MINUTES="$((10#${BASH_REMATCH[2]}))"
WALLTIME_SECONDS="$((10#${BASH_REMATCH[3]}))"
if ((WALLTIME_HOURS > 72)) ||
    ((WALLTIME_HOURS == 72 && (WALLTIME_MINUTES > 0 || WALLTIME_SECONDS > 0))); then
    printf 'ERROR: --time exceeds the cluster maximum of 72:00:00.\n' >&2
    exit 2
fi
command -v sbatch >/dev/null 2>&1 || { printf 'ERROR: sbatch is unavailable.\n' >&2; exit 2; }
[[ -x "${SBATCH_SCRIPT}" ]] || { printf 'ERROR: missing %s\n' "${SBATCH_SCRIPT}" >&2; exit 2; }
[[ -x "${RUNNER}" ]] || { printf 'ERROR: missing %s\n' "${RUNNER}" >&2; exit 2; }

if ! RUN_ROOT="$("${RUNNER}" --resolve-run-root "${PIPELINE_ARGS[@]}")"; then
    printf 'ERROR: submission preflight could not resolve the run directory.\n' >&2
    exit 2
fi
if [[ -z "${LOG_DIR}" ]]; then
    LOG_DIR="${RUN_ROOT}/slurm_logs"
fi
mkdir -p -- "${LOG_DIR}"

SBATCH_RESULT="$(env -u SLURM_CPUS_PER_TASK sbatch \
    --parsable \
    --account="${ACCOUNT}" \
    --partition="${PARTITION}" \
    --mem="${MEMORY}" \
    --time="${WALLTIME}" \
    --cpus-per-task="${CPUS}" \
    --export="ALL,E3_REQUESTED_CPUS=${CPUS}" \
    --job-name="${JOB_NAME}" \
    --output="${LOG_DIR}/%x_%j.out" \
    --error="${LOG_DIR}/%x_%j.err" \
    "${SBATCH_SCRIPT}" "${RUNNER}" "${PIPELINE_ARGS[@]}")"

JOB_ID="${SBATCH_RESULT%%;*}"
[[ "${JOB_ID}" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: sbatch returned an unexpected job identifier: %s\n' "${SBATCH_RESULT}" >&2
    exit 2
}

printf 'Submitted batch job %s\n' "${JOB_ID}"
printf 'Run directory: %s\n' "${RUN_ROOT}"
printf 'Slurm stdout: %s/%s_%s.out\n' "${LOG_DIR}" "${JOB_NAME}" "${JOB_ID}"
printf 'Slurm stderr: %s/%s_%s.err\n' "${LOG_DIR}" "${JOB_NAME}" "${JOB_ID}"
printf 'Monitor: squeue --job %s\n' "${JOB_ID}"
