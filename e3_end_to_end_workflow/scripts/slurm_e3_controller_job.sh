#!/usr/bin/env bash
# Execute the Snakemake controller inside its own small Slurm allocation.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly RUNNER="${SCRIPT_DIR}/run_e3_end_to_end.sh"
CONFIG=""
CONDA_EXECUTABLE=""
CONDA_ENVIRONMENT=""
declare -a RUNNER_ARGS=()

usage() {
    cat <<'EOF'
Usage: slurm_e3_controller_job.sh --config PATH --conda-executable PATH
                                  --conda-environment NAME [-- workflow options]

This is the internal Slurm job body. Users should normally invoke
submit_e3_controller_slurm.sh or the repository-root run_e3_pipeline.sh.
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
        --conda-executable)
            require_option_value "$1" "${2-}"
            CONDA_EXECUTABLE="$2"
            shift 2
            ;;
        --conda-environment)
            require_option_value "$1" "${2-}"
            CONDA_ENVIRONMENT="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            RUNNER_ARGS+=("$@")
            break
            ;;
        *)
            printf 'ERROR: unknown controller-job option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

[[ -n "${SLURM_JOB_ID:-}" ]] || {
    printf 'ERROR: this script must run inside a Slurm batch allocation.\n' >&2
    exit 2
}
[[ -f "${CONFIG}" ]] || {
    printf 'ERROR: config not found: %s\n' "${CONFIG}" >&2
    exit 2
}
[[ -x "${CONDA_EXECUTABLE}" ]] || {
    printf 'ERROR: conda executable is unavailable: %s\n' "${CONDA_EXECUTABLE}" >&2
    exit 2
}
[[ "${CONDA_ENVIRONMENT}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf 'ERROR: unsafe Conda environment name: %s\n' "${CONDA_ENVIRONMENT}" >&2
    exit 2
}
[[ -x "${RUNNER}" ]] || {
    printf 'ERROR: workflow runner is not executable: %s\n' "${RUNNER}" >&2
    exit 2
}

CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"
CONDA_RUN=(
    "${CONDA_EXECUTABLE}"
    run
    --no-capture-output
    --name
    "${CONDA_ENVIRONMENT}"
)
"${CONDA_RUN[@]}" e3-workflow diagnose-install \
    --source-root "${SCRIPT_DIR}" \
    --require-source-match >/dev/null
"${CONDA_RUN[@]}" e3-workflow validate --config "${CONFIG}" >/dev/null
RUN_ROOT="$("${CONDA_RUN[@]}" e3-workflow run-root --config "${CONFIG}")"
CONTROL_DIRECTORY="${RUN_ROOT}/workflow_control"
LOCK_FILE="${CONTROL_DIRECTORY}/controller.lock"
mkdir -p -- "${CONTROL_DIRECTORY}" "${RUN_ROOT}/workflow_logs"

exec 9>"${LOCK_FILE}"
if ! flock --nonblock 9; then
    printf 'ERROR: another controller already owns run %s.\n' "${RUN_ROOT}" >&2
    exit 75
fi

printf '%s INFO Controller Slurm job: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_JOB_ID}"
printf '%s INFO Host: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$(hostname --fqdn)"
printf '%s INFO Conda executable: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CONDA_EXECUTABLE}"
printf '%s INFO Conda environment: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CONDA_ENVIRONMENT}"
"${CONDA_RUN[@]}" python --version
"${CONDA_RUN[@]}" e3-workflow --version

CONTROLLER_COMMAND=(
    "${CONDA_RUN[@]}"
    "${RUNNER}"
    --config
    "${CONFIG}"
    --profile
    slurm
    --allow-inside-slurm
    "${RUNNER_ARGS[@]}"
)
printf 'Controller command:'
printf ' %q' "${CONTROLLER_COMMAND[@]}"
printf '\n'

set +e
"${CONTROLLER_COMMAND[@]}"
CONTROLLER_STATUS="$?"
set -e
printf '%s INFO Controller finished with exit status %s.\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CONTROLLER_STATUS}"
exit "${CONTROLLER_STATUS}"
