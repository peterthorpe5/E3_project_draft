#!/usr/bin/env bash
# Submit the Snakemake controller itself as a durable Slurm batch job.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CONTROLLER_JOB="${SCRIPT_DIR}/scripts/slurm_e3_controller_job.sh"
CONFIG=""
STATUS_ONLY="false"
CONTROLLER_ACCOUNT=""
CONTROLLER_PARTITION=""
CONTROLLER_MEMORY_MB="4000"
CONTROLLER_RUNTIME="3-00:00:00"
CONDA_ENVIRONMENT="e3_end_to_end_workflow"
CONDA_EXECUTABLE="${CONDA_EXE:-}"
CHILD_ACCOUNT="barton"
CHILD_PARTITION="general"
readonly MINIMUM_SQUEUE_RETENTION_SECONDS="120"
SCHEDULER_QUERY_TIMEOUT_SECONDS="15"
SUBMITTED_JOB_ID=""
declare -a RUNNER_ARGS=()

if [[ -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" != "base" ]]; then
    CONDA_ENVIRONMENT="${CONDA_DEFAULT_ENV}"
fi

report_unexpected_error() {
    local exit_status="$1"
    local line_number="$2"
    local failed_command="$3"
    printf 'ERROR: controller launcher stopped unexpectedly at line %s '\
'(exit status %s): %s\n' \
        "${line_number}" "${exit_status}" "${failed_command}" >&2
    if [[ -n "${SUBMITTED_JOB_ID}" ]]; then
        printf 'IMPORTANT: Slurm accepted controller job %s before the launcher error. '\
'Check it with: squeue --jobs %s\n' \
            "${SUBMITTED_JOB_ID}" "${SUBMITTED_JOB_ID}" >&2
    fi
}

trap 'report_unexpected_error "$?" "${LINENO}" "${BASH_COMMAND}"' ERR

usage() {
    cat <<'EOF'
Usage: submit_e3_controller_slurm.sh --config PATH [workflow options]
       submit_e3_controller_slurm.sh --config PATH --status

Required:
  --config PATH                 Immutable workflow YAML.

Controller allocation:
  --controller-account NAME     Slurm account (default: value of --account).
  --controller-partition NAME   Slurm partition (default: value of --partition).
  --controller-memory-mb INT    Controller memory in MiB (default: 4000).
  --controller-runtime TIME     Controller walltime (default: 3-00:00:00).
  --conda-environment NAME      Conda environment (default: active environment or
                                e3_end_to_end_workflow).
  --conda-executable PATH       Conda executable (default: CONDA_EXE or PATH).
  --scheduler-query-timeout-seconds INT
                                Hard limit for each scheduler query (default: 15).
  --status                      Report the submitted controller job state.
  --help                        Show this help text.
  --version                     Show the package version.

Scientific-job defaults:
  --account NAME                Child-job Slurm account (default: barton).
  --partition NAME              Child-job Slurm partition (default: general).

All other named workflow options are forwarded unchanged to run_e3_end_to_end.sh.
The submitted controller holds the same per-run lock as the legacy detached launcher,
runs Snakemake with the Slurm executor, and may safely continue after logout.
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

validate_scheduler_name() {
    local option_name="$1"
    local supplied_value="$2"
    if [[ ! "${supplied_value}" =~ ^[A-Za-z0-9._-]+$ ]]; then
        printf 'ERROR: %s contains unsafe characters: %s\n' \
            "${option_name}" "${supplied_value}" >&2
        exit 2
    fi
}

validate_squeue_retention() {
    local configuration_line
    local count
    local suffix
    local unit
    local seconds
    if ! command -v scontrol >/dev/null; then
        printf 'WARNING: scontrol is unavailable; Slurm MinJobAge could not be verified. '\
'Continuing because this advisory query is not required for submission.\n' >&2
        return 0
    fi
    if configuration_line="$(
        timeout --signal=KILL "${SCHEDULER_QUERY_TIMEOUT_SECONDS}s" \
            scontrol show config 2>/dev/null |
            awk '$1 == "MinJobAge" {print $3, $4; exit}'
    )"; then
        :
    else
        printf 'WARNING: scontrol could not verify MinJobAge within %s seconds. '\
'Continuing because this advisory query is not required for submission.\n' \
            "${SCHEDULER_QUERY_TIMEOUT_SECONDS}" >&2
        return 0
    fi
    [[ -n "${configuration_line}" ]] || {
        printf 'WARNING: scontrol did not report MinJobAge. Continuing because this '\
'advisory query is not required for submission.\n' >&2
        return 0
    }
    read -r count unit <<<"${configuration_line}"
    if [[ "${count}" =~ ^([0-9]+)([A-Za-z]*)$ ]]; then
        count="${BASH_REMATCH[1]}"
        suffix="${BASH_REMATCH[2],,}"
    else
        printf 'WARNING: unsupported Slurm MinJobAge value: %s. Continuing because this '\
'advisory query is not required for submission.\n' \
            "${configuration_line}" >&2
        return 0
    fi
    [[ -n "${suffix}" ]] || suffix="${unit,,}"
    case "${suffix}" in
        ""|s|sec|secs|second|seconds)
            seconds="${count}"
            ;;
        m|min|mins|minute|minutes)
            seconds="$((count * 60))"
            ;;
        h|hour|hours)
            seconds="$((count * 3600))"
            ;;
        *)
            printf 'WARNING: unsupported Slurm MinJobAge unit: %s. Continuing because '\
'this advisory query is not required for submission.\n' "${suffix}" >&2
            return 0
            ;;
    esac
    if ((seconds < MINIMUM_SQUEUE_RETENTION_SECONDS)); then
        printf 'ERROR: Slurm MinJobAge is %s seconds; the squeue status backend requires '\
'at least %s seconds for reliable completed-job detection.\n' \
            "${seconds}" "${MINIMUM_SQUEUE_RETENTION_SECONDS}" >&2
        return 2
    fi
}

while (($#)); do
    case "$1" in
        --config)
            require_option_value "$1" "${2-}"
            CONFIG="$2"
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
        --scheduler-query-timeout-seconds)
            require_option_value "$1" "${2-}"
            SCHEDULER_QUERY_TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        --account)
            require_option_value "$1" "${2-}"
            CHILD_ACCOUNT="$2"
            RUNNER_ARGS+=("$1" "$2")
            shift 2
            ;;
        --partition)
            require_option_value "$1" "${2-}"
            CHILD_PARTITION="$2"
            RUNNER_ARGS+=("$1" "$2")
            shift 2
            ;;
        --profile)
            printf 'ERROR: the Slurm controller always uses the slurm profile.\n' >&2
            exit 2
            ;;
        --status)
            STATUS_ONLY="true"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --version)
            "${SCRIPT_DIR}/run_e3_end_to_end.sh" --version
            exit 0
            ;;
        --)
            shift
            RUNNER_ARGS+=(-- "$@")
            break
            ;;
        *)
            RUNNER_ARGS+=("$1")
            shift
            ;;
    esac
done

[[ -n "${CONFIG}" ]] || {
    printf 'ERROR: --config is required.\n' >&2
    usage >&2
    exit 2
}
[[ -f "${CONFIG}" ]] || {
    printf 'ERROR: config not found: %s\n' "${CONFIG}" >&2
    exit 2
}
[[ -z "${SLURM_JOB_ID:-}" ]] || {
    printf 'ERROR: submit the controller from a login node, not Slurm job %s.\n' \
        "${SLURM_JOB_ID}" >&2
    exit 2
}
[[ "${CONTROLLER_MEMORY_MB}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --controller-memory-mb must be a positive integer.\n' >&2
    exit 2
}
[[ "${CONTROLLER_RUNTIME}" =~ ^([0-9]+-)?[0-9]{1,2}:[0-9]{2}:[0-9]{2}$ ]] || {
    printf 'ERROR: --controller-runtime must use Slurm D-HH:MM:SS or HH:MM:SS format.\n' >&2
    exit 2
}
[[ "${CONDA_ENVIRONMENT}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf 'ERROR: --conda-environment contains unsafe characters.\n' >&2
    exit 2
}
[[ "${SCHEDULER_QUERY_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --scheduler-query-timeout-seconds must be a positive integer.\n' >&2
    exit 2
}
((SCHEDULER_QUERY_TIMEOUT_SECONDS <= 300)) || {
    printf 'ERROR: --scheduler-query-timeout-seconds must not exceed 300.\n' >&2
    exit 2
}
validate_scheduler_name "--account" "${CHILD_ACCOUNT}"
validate_scheduler_name "--partition" "${CHILD_PARTITION}"
CONTROLLER_ACCOUNT="${CONTROLLER_ACCOUNT:-${CHILD_ACCOUNT}}"
CONTROLLER_PARTITION="${CONTROLLER_PARTITION:-${CHILD_PARTITION}}"
validate_scheduler_name "--controller-account" "${CONTROLLER_ACCOUNT}"
validate_scheduler_name "--controller-partition" "${CONTROLLER_PARTITION}"

for command_name in flock; do
    command -v "${command_name}" >/dev/null || {
        printf 'ERROR: required command is not on PATH: %s\n' "${command_name}" >&2
        exit 2
    }
done
if [[ -z "${CONDA_EXECUTABLE}" ]]; then
    CONDA_EXECUTABLE="$(command -v conda || true)"
fi
[[ -n "${CONDA_EXECUTABLE}" && -x "${CONDA_EXECUTABLE}" ]] || {
    printf 'ERROR: conda executable not found; activate Conda or use --conda-executable.\n' >&2
    exit 2
}
CONDA_DIRECTORY="$(cd -- "$(dirname -- "${CONDA_EXECUTABLE}")" && pwd -P)"
CONDA_EXECUTABLE="${CONDA_DIRECTORY}/$(basename -- "${CONDA_EXECUTABLE}")"
CONDA_RUN=(
    "${CONDA_EXECUTABLE}"
    run
    --no-capture-output
    --name
    "${CONDA_ENVIRONMENT}"
)

CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"
"${CONDA_RUN[@]}" e3-workflow diagnose-install \
    --source-root "${SCRIPT_DIR}" \
    --require-source-match >/dev/null
"${CONDA_RUN[@]}" e3-workflow validate --config "${CONFIG}" >/dev/null
RUN_ROOT="$("${CONDA_RUN[@]}" e3-workflow run-root --config "${CONFIG}")"
RUN_NAME="$(basename -- "${RUN_ROOT}")"
CONTROL_DIRECTORY="${RUN_ROOT}/workflow_control"
LOG_DIRECTORY="${RUN_ROOT}/workflow_logs"
METADATA_FILE="${CONTROL_DIRECTORY}/controller.slurm.tsv"
SUBMISSION_LOCK="${CONTROL_DIRECTORY}/controller_submission.lock"
mkdir -p -- "${CONTROL_DIRECTORY}" "${LOG_DIRECTORY}"

read_job_id() {
    local job_id
    if [[ ! -s "${METADATA_FILE}" ]]; then
        return 0
    fi
    job_id="$(awk -F '\t' 'NR == 2 {print $1; exit}' "${METADATA_FILE}")"
    if [[ ! "${job_id}" =~ ^[1-9][0-9]*$ ]]; then
        printf 'ERROR: controller metadata does not contain a valid Slurm job ID: %s\n' \
            "${METADATA_FILE}" >&2
        return 2
    fi
    printf '%s\n' "${job_id}"
}

squeue_diagnostic_means_job_absent() {
    local diagnostic="$1"
    [[ "${diagnostic,,}" =~ invalid[[:space:]]+job[[:space:]]+id([[:space:]]+specified)? ]]
}

query_squeue_state() {
    local job_id="$1"
    local output
    local state
    command -v squeue >/dev/null || {
        printf 'ERROR: required Slurm command is not on PATH: squeue\n' >&2
        return 2
    }
    command -v timeout >/dev/null || {
        printf 'ERROR: required command is not on PATH: timeout\n' >&2
        return 2
    }
    if output="$(
        timeout --signal=KILL "${SCHEDULER_QUERY_TIMEOUT_SECONDS}s" \
            squeue --noheader --jobs "${job_id}" --format '%T' 2>&1
    )"; then
        state="$(awk 'NF {print $1; exit}' <<<"${output}")"
        printf '%s\n' "${state}"
        return 0
    fi
    if squeue_diagnostic_means_job_absent "${output}"; then
        return 0
    fi
    output="$(awk 'NF {print; exit}' <<<"${output}")"
    printf 'ERROR: squeue could not determine whether controller job %s is active: %s\n' \
        "${job_id}" "${output:-no scheduler diagnostic was returned}" >&2
    return 2
}

query_sacct_state() {
    local job_id="$1"
    local output
    local state
    command -v sacct >/dev/null || return 1
    command -v timeout >/dev/null || return 1
    if output="$(
        timeout --signal=KILL "${SCHEDULER_QUERY_TIMEOUT_SECONDS}s" \
            sacct --noheader --parsable2 --jobs "${job_id}" \
            --format State 2>/dev/null
    )"; then
        state="$(awk -F '|' 'NF && $1 != "" {print $1; exit}' <<<"${output}")"
        state="${state%%+*}"
        [[ -z "${state}" ]] || {
            printf '%s\n' "${state}"
            return 0
        }
    fi
    return 1
}

controller_is_active() {
    local state="$1"
    case "${state}" in
        PENDING|RUNNING|CONFIGURING|COMPLETING|REQUEUED|REQUEUE_FED|\
REQUEUE_HOLD|RESIZING|RESV_DEL_HOLD|SIGNALING|STAGE_OUT|STOPPED|SUSPENDED)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

controller_is_terminal() {
    local state="$1"
    case "${state}" in
        BOOT_FAIL|CANCELLED|COMPLETED|DEADLINE|FAILED|NODE_FAIL|\
OUT_OF_MEMORY|PREEMPTED|REVOKED|TIMEOUT)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

controller_status() {
    local job_id
    local status_source
    local state
    if job_id="$(read_job_id)"; then
        :
    else
        printf 'Run: %s\nController: METADATA_INVALID\nMetadata: %s\n' \
            "${RUN_NAME}" "${METADATA_FILE}"
        return 2
    fi
    if [[ -z "${job_id}" ]]; then
        printf 'Run: %s\nController: NOT_SUBMITTED\nMetadata: %s\n' \
            "${RUN_NAME}" "${METADATA_FILE}"
        return 1
    fi
    if state="$(query_squeue_state "${job_id}")"; then
        status_source="squeue"
    else
        printf 'Run: %s\nController: STATUS_QUERY_FAILED\nSlurm job: %s\nMetadata: %s\n' \
            "${RUN_NAME}" "${job_id}" "${METADATA_FILE}"
        return 2
    fi
    if [[ -z "${state}" ]]; then
        if state="$(query_sacct_state "${job_id}")"; then
            status_source="sacct"
        else
            state="NOT_IN_QUEUE"
            status_source="squeue"
        fi
    fi
    printf 'Run: %s\nController: %s\nSlurm job: %s\nStatus source: %s\nMetadata: %s\n' \
        "${RUN_NAME}" "${state}" "${job_id}" "${status_source}" "${METADATA_FILE}"
    if [[ "${state}" == "NOT_IN_QUEUE" ]]; then
        printf 'Accounting: UNAVAILABLE_OR_NO_RECORD\n'
    fi
    controller_is_active "${state}"
}

if [[ "${STATUS_ONLY}" == "true" ]]; then
    controller_status || true
    exit 0
fi

"${CONDA_RUN[@]}" e3-workflow diagnose-slurm-executor \
    --require-compatible >/dev/null
for command_name in sbatch squeue timeout; do
    command -v "${command_name}" >/dev/null || {
        printf 'ERROR: required Slurm command is not on PATH: %s\n' "${command_name}" >&2
        exit 2
    }
done
if validate_squeue_retention; then
    :
else
    RETENTION_STATUS="$?"
    exit "${RETENTION_STATUS}"
fi
[[ -x "${CONTROLLER_JOB}" ]] || {
    printf 'ERROR: controller job script is not executable: %s\n' "${CONTROLLER_JOB}" >&2
    exit 2
}

exec 9>"${SUBMISSION_LOCK}"
if ! flock --nonblock 9; then
    printf 'ERROR: another controller submission is in progress for %s.\n' \
        "${RUN_NAME}" >&2
    exit 3
fi
printf 'E3 controller submission preflight passed.\n'
printf 'Run: %s\n' "${RUN_NAME}"
printf 'Configuration: %s\n' "${CONFIG}"
printf 'Status backend for scientific jobs: squeue\n'

if PRIOR_JOB_ID="$(read_job_id)"; then
    :
else
    exit 2
fi
if [[ -n "${PRIOR_JOB_ID}" ]]; then
    if PRIOR_STATE="$(query_squeue_state "${PRIOR_JOB_ID}")"; then
        :
    else
        printf 'ERROR: refusing to submit while the prior controller state is unknown.\n' >&2
        exit 3
    fi
    if controller_is_active "${PRIOR_STATE}"; then
        printf 'ERROR: a Slurm controller is already active for %s.\n' "${RUN_NAME}" >&2
        printf 'Controller: %s\nSlurm job: %s\nStatus source: squeue\n' \
            "${PRIOR_STATE}" "${PRIOR_JOB_ID}" >&2
        exit 3
    fi
    if [[ -n "${PRIOR_STATE}" ]] && ! controller_is_terminal "${PRIOR_STATE}"; then
        printf 'ERROR: refusing to submit because squeue returned an unrecognised '\
'controller state for job %s: %s\n' \
            "${PRIOR_JOB_ID}" "${PRIOR_STATE}" >&2
        exit 3
    fi
    printf 'Previous controller job %s is not active in squeue; safe resume is permitted.\n' \
        "${PRIOR_JOB_ID}"
fi

SAFE_RUN_NAME="${RUN_NAME//[^A-Za-z0-9_-]/_}"
SAFE_RUN_NAME="${SAFE_RUN_NAME:0:80}"
SLURM_LOG="${LOG_DIRECTORY}/controller_slurm_%j.log"
SBATCH_COMMAND=(
    sbatch
    --parsable
    --job-name "e3ctl_${SAFE_RUN_NAME}"
    --account "${CONTROLLER_ACCOUNT}"
    --partition "${CONTROLLER_PARTITION}"
    --cpus-per-task 1
    --mem "${CONTROLLER_MEMORY_MB}M"
    --time "${CONTROLLER_RUNTIME}"
    --chdir "${SCRIPT_DIR}"
    --output "${SLURM_LOG}"
    --error "${SLURM_LOG}"
    --signal "B:TERM@120"
    "${CONTROLLER_JOB}"
    --source-root "${SCRIPT_DIR}"
    --config "${CONFIG}"
    --conda-executable "${CONDA_EXECUTABLE}"
    --conda-environment "${CONDA_ENVIRONMENT}"
    --
    "${RUNNER_ARGS[@]}"
)
if SBATCH_RESPONSE="$("${SBATCH_COMMAND[@]}")"; then
    :
else
    SBATCH_STATUS="$?"
    printf 'ERROR: sbatch rejected the E3 controller submission (exit status %s).\n' \
        "${SBATCH_STATUS}" >&2
    exit "${SBATCH_STATUS}"
fi
JOB_ID="${SBATCH_RESPONSE%%;*}"
[[ "${JOB_ID}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: sbatch returned an invalid job identifier: %s\n' "${SBATCH_RESPONSE}" >&2
    exit 1
}
SUBMITTED_JOB_ID="${JOB_ID}"

METADATA_TEMP="${METADATA_FILE}.partial.$$"
{
    printf 'job_id\tsubmitted_at_utc\trun_name\tconfiguration\tcontroller_log\t'
    printf 'conda_environment\tcontroller_account\tcontroller_partition\n'
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "${JOB_ID}" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        "${RUN_NAME}" \
        "${CONFIG}" \
        "${SLURM_LOG//%j/${JOB_ID}}" \
        "${CONDA_ENVIRONMENT}" \
        "${CONTROLLER_ACCOUNT}" \
        "${CONTROLLER_PARTITION}"
} >"${METADATA_TEMP}"
mv -- "${METADATA_TEMP}" "${METADATA_FILE}"

printf 'Submitted E3 Snakemake controller to Slurm.\n'
printf 'Run: %s\n' "${RUN_NAME}"
printf 'Controller job: %s\n' "${JOB_ID}"
printf 'Controller log: %s\n' "${SLURM_LOG//%j/${JOB_ID}}"
printf 'Status: %s --config %s --status\n' "$0" "${CONFIG}"
printf 'Queue: squeue --jobs %s\n' "${JOB_ID}"
