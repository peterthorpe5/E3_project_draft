#!/usr/bin/env bash
# Submit the human-and-plant Snakemake controller as a durable Slurm job.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CONTROLLER_SCRIPT="${SCRIPT_DIR}/scripts/slurm_human_plant_extension_controller.sh"
readonly RUNNER="${SCRIPT_DIR}/run_human_plant_structural_extension.sh"
CONFIG=""
CONDA_ENVIRONMENT="e3_end_to_end_workflow"
CONDA_EXECUTABLE="${CONDA_EXE:-}"
CONTROLLER_ACCOUNT="barton"
CONTROLLER_PARTITION="barton"
CONTROLLER_MEMORY_MB="4000"
CONTROLLER_RUNTIME="3-00:00:00"
CONTROLLER_LOG_DIR="${PWD}"
MAX_JOBS="50"
CHILD_ACCOUNT="barton"
CHILD_PARTITION="barton"
declare -a EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: submit_human_plant_extension_slurm.sh --config PATH [options]

Required:
  --config PATH                 Human-and-plant extension YAML.

Controller allocation:
  --conda-environment NAME      Workflow environment (default: e3_end_to_end_workflow).
  --conda-executable PATH       Conda executable (default: CONDA_EXE or PATH).
  --controller-account NAME     Controller account (default: barton).
  --controller-partition NAME   Controller partition (default: barton).
  --controller-memory-mb INT    Controller memory in MiB (default: 4000).
  --controller-runtime TIME     Controller walltime (default: 3-00:00:00).
  --controller-log-dir PATH     Durable log directory (default: current directory).

Scientific jobs:
  --max-jobs INTEGER            Maximum concurrent jobs (default: 50).
  --account NAME                Child-job account (default: barton).
  --partition NAME              Child-job partition (default: barton).
  --help                        Show this help text.
  --                            Forward remaining arguments to the extension runner.

The submitted controller continues after logout and delegates scientific jobs
to the existing Snakemake Slurm profile.
EOF
}

require_option_value() {
    local option_name="$1"
    local supplied_value="${2-}"
    if [[ -z "${supplied_value}" || "${supplied_value}" == --* ]]; then
        printf 'ERROR: %s requires a value.\n' "${option_name}" >&2
        exit 2
    fi
}

while (($#)); do
    case "$1" in
        --config)
            require_option_value "$1" "${2-}"
            CONFIG="$2"
            shift 2
            ;;
        --conda-environment)
            require_option_value "$1" "${2-}"
            CONDA_ENVIRONMENT="$2"
            shift 2
            ;;
        --conda-executable)
            require_option_value "$1" "${2-}"
            CONDA_EXECUTABLE="$2"
            shift 2
            ;;
        --controller-account)
            require_option_value "$1" "${2-}"
            CONTROLLER_ACCOUNT="$2"
            shift 2
            ;;
        --controller-partition)
            require_option_value "$1" "${2-}"
            CONTROLLER_PARTITION="$2"
            shift 2
            ;;
        --controller-memory-mb)
            require_option_value "$1" "${2-}"
            CONTROLLER_MEMORY_MB="$2"
            shift 2
            ;;
        --controller-runtime)
            require_option_value "$1" "${2-}"
            CONTROLLER_RUNTIME="$2"
            shift 2
            ;;
        --controller-log-dir)
            require_option_value "$1" "${2-}"
            CONTROLLER_LOG_DIR="$2"
            shift 2
            ;;
        --max-jobs)
            require_option_value "$1" "${2-}"
            MAX_JOBS="$2"
            shift 2
            ;;
        --account)
            require_option_value "$1" "${2-}"
            CHILD_ACCOUNT="$2"
            shift 2
            ;;
        --partition)
            require_option_value "$1" "${2-}"
            CHILD_PARTITION="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS+=("$@")
            break
            ;;
        *)
            printf 'ERROR: unknown option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

[[ -n "${CONFIG}" && -f "${CONFIG}" ]] || {
    printf 'ERROR: --config must name an existing file.\n' >&2
    exit 2
}
[[ "${MAX_JOBS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --max-jobs must be a positive integer.\n' >&2
    exit 2
}
[[ "${CONTROLLER_MEMORY_MB}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --controller-memory-mb must be positive.\n' >&2
    exit 2
}
for scheduler_name in \
    "${CONTROLLER_ACCOUNT}" "${CONTROLLER_PARTITION}" \
    "${CHILD_ACCOUNT}" "${CHILD_PARTITION}"; do
    [[ "${scheduler_name}" =~ ^[A-Za-z0-9._-]+$ ]] || {
        printf 'ERROR: Slurm account or partition contains unsafe characters.\n' >&2
        exit 2
    }
done
command -v sbatch >/dev/null || {
    printf 'ERROR: sbatch is not available.\n' >&2
    exit 2
}
command -v squeue >/dev/null || {
    printf 'ERROR: squeue is not available.\n' >&2
    exit 2
}
if [[ -z "${CONDA_EXECUTABLE}" ]]; then
    CONDA_EXECUTABLE="$(command -v conda || true)"
fi
[[ -n "${CONDA_EXECUTABLE}" && -x "${CONDA_EXECUTABLE}" ]] || {
    printf 'ERROR: provide an executable Conda path with --conda-executable.\n' >&2
    exit 2
}
[[ -x "${CONTROLLER_SCRIPT}" && -x "${RUNNER}" ]] || {
    printf 'ERROR: extension controller scripts are not executable.\n' >&2
    exit 2
}

CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"
mkdir -p -- "${CONTROLLER_LOG_DIR}"
CONTROLLER_LOG_DIR="$(cd -- "${CONTROLLER_LOG_DIR}" && pwd -P)"
CONFIG_BASENAME="$(basename -- "${CONFIG}")"
STATE_KEY="${CONFIG_BASENAME//[^A-Za-z0-9._-]/_}"
STATE_FILE="${CONTROLLER_LOG_DIR}/.${STATE_KEY}.human_plant_controller.tsv"
SUBMISSION_LOCK="${CONTROLLER_LOG_DIR}/.${STATE_KEY}.submission.lock"
if ! mkdir -- "${SUBMISSION_LOCK}" 2>/dev/null; then
    printf 'ERROR: another controller submission is in progress for %s.\n' \
        "${CONFIG}" >&2
    exit 2
fi
release_submission_lock() {
    rmdir -- "${SUBMISSION_LOCK}" 2>/dev/null || true
}
trap release_submission_lock EXIT
if [[ -s "${STATE_FILE}" ]]; then
    PREVIOUS_JOB_ID="$(awk -F '\t' 'NR == 2 {print $1}' "${STATE_FILE}")"
    if [[ "${PREVIOUS_JOB_ID}" =~ ^[0-9]+$ ]]; then
        if ! ACTIVE_STATE="$(
            squeue --noheader --jobs "${PREVIOUS_JOB_ID}" --format '%T'
        )"; then
            printf 'ERROR: could not query previous controller job %s.\n' \
                "${PREVIOUS_JOB_ID}" >&2
            exit 2
        fi
        if [[ -n "${ACTIVE_STATE//[[:space:]]/}" ]]; then
            printf 'ERROR: controller job %s is still active (%s).\n' \
                "${PREVIOUS_JOB_ID}" "${ACTIVE_STATE}" >&2
            exit 2
        fi
    fi
fi

SBATCH_COMMAND=(
    sbatch
    --parsable
    --job-name e3-human-plant-controller
    --account "${CONTROLLER_ACCOUNT}"
    --partition "${CONTROLLER_PARTITION}"
    --cpus-per-task 1
    --mem "${CONTROLLER_MEMORY_MB}M"
    --time "${CONTROLLER_RUNTIME}"
    --output "${CONTROLLER_LOG_DIR}/human_plant_controller_%j.log"
    --error "${CONTROLLER_LOG_DIR}/human_plant_controller_%j.log"
    "${CONTROLLER_SCRIPT}"
    "${CONDA_EXECUTABLE}"
    "${CONDA_ENVIRONMENT}"
    "${RUNNER}"
    --config "${CONFIG}"
    --profile slurm
    --max-jobs "${MAX_JOBS}"
    --account "${CHILD_ACCOUNT}"
    --partition "${CHILD_PARTITION}"
)
SBATCH_COMMAND+=("${EXTRA_ARGS[@]}")
JOB_ID="$("${SBATCH_COMMAND[@]}")"
JOB_ID="${JOB_ID%%;*}"
[[ "${JOB_ID}" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: sbatch returned an invalid job identifier: %s\n' \
        "${JOB_ID}" >&2
    exit 2
}
printf 'job_id\tconfig\tsubmitted_at\n%s\t%s\t%s\n' \
    "${JOB_ID}" "${CONFIG}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "${STATE_FILE}"
printf 'Submitted human-and-plant extension controller: %s\n' "${JOB_ID}"
printf 'Status: squeue --jobs %q\n' "${JOB_ID}"
printf 'Log: %s/human_plant_controller_%s.log\n' \
    "${CONTROLLER_LOG_DIR}" "${JOB_ID}"
