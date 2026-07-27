#!/usr/bin/env bash
# Single repository-root entry point for the complete E3 workflow.

set -Eeuo pipefail

readonly REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly WORKFLOW_ROOT="${REPOSITORY_ROOT}/e3_end_to_end_workflow"
readonly RELEASE_VERSION="$(
    awk -F '"' '/^version = "[0-9][0-9.]*"$/ {print $2; exit}' \
        "${WORKFLOW_ROOT}/pyproject.toml"
)"
MODE="slurm"
CONFIG=""
STATUS_ONLY="false"
PASSTHROUGH="false"
declare -a WORKFLOW_ARGS=()

usage() {
    cat <<'EOF'
Usage: run_e3_pipeline.sh --config PATH [options]

Repository-level controls:
  --config PATH          Immutable end-to-end workflow YAML (required).
  --mode MODE            slurm, local, or login-detached (default: slurm).
  --status               Report controller status; valid for slurm/login-detached.
  --version              Show this repository launcher version.
  --help                 Show this help text.

Common workflow controls:
  --threads INTEGER      Local CPU budget.
  --max-jobs INTEGER     Maximum concurrent scientific Slurm jobs.
  --account NAME         Scientific-job Slurm account.
  --partition NAME       Scientific-job Slurm partition.
  --resume               Reuse checksum-validated completed stages.
  --start-at STAGE       Intentionally rerun from a named stage.
  --stop-after STAGE     Run only through a named stage.
  --force-stage STAGE    Intentionally rerun one named stage; repeatable.
  --dry-run              Validate and show the execution plan.

Modes:
  slurm                  Submit the Snakemake controller as a small Slurm batch
                         job. It continues after logout and submits scientific
                         stage jobs through the Snakemake Slurm executor.
  local                  Run the complete enabled DAG in the foreground without
                         Slurm. Suitable for workstations and synthetic tests.
  login-detached         Legacy nohup/setsid controller on the login node.

Every unrecognised named option is forwarded to the selected workflow launcher.
Running without --stop-after requests the entire enabled end-to-end DAG.
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
        --mode)
            require_option_value "$1" "${2-}"
            MODE="$2"
            shift 2
            ;;
        --status)
            STATUS_ONLY="true"
            shift
            ;;
        --profile)
            printf 'ERROR: use --mode at repository level; do not supply --profile.\n' >&2
            exit 2
            ;;
        --version)
            printf 'E3 project launcher %s\n' "${RELEASE_VERSION:-UNKNOWN}"
            exit 0
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            PASSTHROUGH="true"
            shift
            WORKFLOW_ARGS+=(-- "$@")
            break
            ;;
        *)
            WORKFLOW_ARGS+=("$1")
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
if [[ "${STATUS_ONLY}" == "true" && "${PASSTHROUGH}" == "true" ]]; then
    printf 'ERROR: --status cannot be combined with raw Snakemake arguments.\n' >&2
    exit 2
fi
CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"

case "${MODE}" in
    slurm)
        ENTRYPOINT="${WORKFLOW_ROOT}/submit_e3_controller_slurm.sh"
        ;;
    local)
        ENTRYPOINT="${WORKFLOW_ROOT}/run_e3_end_to_end.sh"
        if [[ "${STATUS_ONLY}" == "true" ]]; then
            printf 'ERROR: --status is not available for foreground local mode.\n' >&2
            exit 2
        fi
        MODE_ARGS=(--profile local)
        ;;
    login-detached)
        ENTRYPOINT="${WORKFLOW_ROOT}/submit_e3_end_to_end.sh"
        ;;
    *)
        printf 'ERROR: --mode must be slurm, local, or login-detached; observed %s.\n' \
            "${MODE}" >&2
        exit 2
        ;;
esac

if [[ "${MODE}" != "local" ]]; then
    MODE_ARGS=()
fi

[[ -x "${ENTRYPOINT}" ]] || {
    printf 'ERROR: workflow entry point is missing or not executable: %s\n' \
        "${ENTRYPOINT}" >&2
    exit 2
}
[[ "${STATUS_ONLY}" == "false" ]] || WORKFLOW_ARGS+=(--status)
exec "${ENTRYPOINT}" --config "${CONFIG}" "${MODE_ARGS[@]}" "${WORKFLOW_ARGS[@]}"
