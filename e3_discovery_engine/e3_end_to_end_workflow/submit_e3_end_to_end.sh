#!/usr/bin/env bash
# Detach the Snakemake controller on a login node and return immediately.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly RUNNER="${SCRIPT_DIR}/run_e3_end_to_end.sh"
CONFIG=""
STATUS_ONLY="false"
FOREGROUND="false"
PROFILE_SUPPLIED="false"
declare -a RUNNER_ARGS=()

usage() {
    cat <<'EOF'
Usage: submit_e3_end_to_end.sh --config PATH [workflow options]
       submit_e3_end_to_end.sh --config PATH --status

Required:
  --config PATH          Immutable workflow YAML.

Submission controls:
  --status               Report the detached controller state without launching work.
  --foreground           Run synchronously; useful only for dry runs and diagnostics.
  --help                 Show this help text.
  --version              Show the package version.

All other named workflow options are forwarded unchanged to run_e3_end_to_end.sh. The Slurm profile
is added automatically when --profile is omitted. Normal submission uses nohup, setsid and flock:
the lightweight Snakemake controller remains on the login node, scientific jobs run through Slurm,
and only one controller may own a run at a time.
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
        --profile)
            require_option_value "$1" "${2-}"
            PROFILE_SUPPLIED="true"
            RUNNER_ARGS+=("$1" "$2")
            shift 2
            ;;
        --status)
            STATUS_ONLY="true"
            shift
            ;;
        --foreground)
            FOREGROUND="true"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --version)
            "${RUNNER}" --version
            exit 0
            ;;
        --)
            RUNNER_ARGS+=("$@")
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
for command_name in e3-workflow; do
    command -v "${command_name}" >/dev/null || {
        printf 'ERROR: required command is not on PATH: %s\n' "${command_name}" >&2
        exit 2
    }
done

CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"
RUNNER_ARGS=(--config "${CONFIG}" "${RUNNER_ARGS[@]}")
e3-workflow validate --config "${CONFIG}" >/dev/null
RUN_ROOT="$(e3-workflow run-root --config "${CONFIG}")"
RUN_NAME="$(basename -- "${RUN_ROOT}")"
CONTROL_DIRECTORY="${RUN_ROOT}/workflow_control"
LOG_DIRECTORY="${RUN_ROOT}/workflow_logs"
LOCK_FILE="${CONTROL_DIRECTORY}/controller.lock"
PID_FILE="${CONTROL_DIRECTORY}/controller.pid.tsv"
mkdir -p -- "${CONTROL_DIRECTORY}" "${LOG_DIRECTORY}"

controller_status() {
    if [[ ! -s "${PID_FILE}" ]]; then
        printf 'Run: %s\nController: NOT_SUBMITTED\nPID file: %s\n' \
            "${RUN_NAME}" "${PID_FILE}"
        return 1
    fi
    local controller_pid
    controller_pid="$(awk -F '\t' 'NR == 2 {print $1}' "${PID_FILE}")"
    if [[ "${controller_pid}" =~ ^[1-9][0-9]*$ ]] && kill -0 "${controller_pid}" 2>/dev/null; then
        printf 'Run: %s\nController: RUNNING\nPID: %s\nPID file: %s\n' \
            "${RUN_NAME}" "${controller_pid}" "${PID_FILE}"
        return 0
    fi
    printf 'Run: %s\nController: NOT_RUNNING\nLast PID: %s\nPID file: %s\n' \
        "${RUN_NAME}" "${controller_pid:-unknown}" "${PID_FILE}"
    return 1
}

if [[ "${STATUS_ONLY}" == "true" ]]; then
    controller_status || true
    exit 0
fi

for command_name in snakemake nohup setsid flock; do
    command -v "${command_name}" >/dev/null || {
        printf 'ERROR: required command is not on PATH: %s\n' "${command_name}" >&2
        exit 2
    }
done

if [[ "${FOREGROUND}" == "true" ]]; then
    if [[ "${PROFILE_SUPPLIED}" == "false" ]]; then
        RUNNER_ARGS+=(--profile slurm)
    fi
    exec "${RUNNER}" "${RUNNER_ARGS[@]}"
fi

if controller_status >/dev/null 2>&1; then
    printf 'ERROR: a controller is already running for %s.\n' "${RUN_NAME}" >&2
    controller_status >&2
    exit 3
fi
if ! flock --nonblock "${LOCK_FILE}" true; then
    printf 'ERROR: the controller lock is already held for %s.\n' "${RUN_NAME}" >&2
    exit 3
fi
if [[ "${PROFILE_SUPPLIED}" == "false" ]]; then
    RUNNER_ARGS+=(--profile slurm)
fi

TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
SUBMISSION_LOG="${LOG_DIRECTORY}/submission_${TIMESTAMP}.log"
nohup setsid flock --nonblock --conflict-exit-code 75 "${LOCK_FILE}" \
    "${RUNNER}" "${RUNNER_ARGS[@]}" \
    >>"${SUBMISSION_LOG}" 2>&1 </dev/null &
CONTROLLER_PID="$!"

PID_TEMP="${PID_FILE}.partial.$$"
{
    printf 'pid\tstarted_at_utc\trun_name\tconfiguration\tsubmission_log\n'
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "${CONTROLLER_PID}" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        "${RUN_NAME}" \
        "${CONFIG}" \
        "${SUBMISSION_LOG}"
} >"${PID_TEMP}"
mv -- "${PID_TEMP}" "${PID_FILE}"

sleep 1
if ! kill -0 "${CONTROLLER_PID}" 2>/dev/null; then
    wait "${CONTROLLER_PID}" || controller_status_code="$?"
    printf 'ERROR: the detached controller exited during start-up with status %s.\n' \
        "${controller_status_code:-unknown}" >&2
    printf 'Review: %s\n' "${SUBMISSION_LOG}" >&2
    exit 1
fi

printf 'Submitted detached E3 workflow controller.\n'
printf 'Run: %s\n' "${RUN_NAME}"
printf 'Controller PID: %s\n' "${CONTROLLER_PID}"
printf 'Controller log: %s\n' "${SUBMISSION_LOG}"
printf 'Status: %s --config %s --status\n' "$0" "${CONFIG}"
printf 'Watch: tail -f %s\n' "${SUBMISSION_LOG}"
printf 'Scientific jobs: squeue -u %s\n' "${USER}"
