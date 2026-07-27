#!/usr/bin/env bash
# Submit or run the complete E3 workflow without previous analysis authorities.

set -Eeuo pipefail

readonly REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly MASTER_LAUNCHER="${REPOSITORY_ROOT}/run_e3_pipeline.sh"
CONFIG=""
MODE="slurm"
THREADS="32"
MAX_JOBS="10"
ACCOUNT="barton"
PARTITION="general"
RESUME="false"
STATUS_ONLY="false"
DRY_RUN="false"
declare -a EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: run_e3_pipeline_fresh.sh --config PATH [options]

Required:
  --config PATH          Schema-v2 complete fresh-production YAML.

Execution:
  --mode MODE            slurm or local (default: slurm).
  --threads INTEGER      Local CPU budget (default: 32).
  --max-jobs INTEGER     Concurrent scientific Slurm jobs, 1-10 (default: 10).
  --account NAME         Slurm account (default: barton).
  --partition NAME       Slurm partition (default: general).
  --resume               Continue the same checksum-bound fresh run.
  --status               Report the durable Slurm controller state.
  --dry-run              Validate and display the complete DAG without running it.
  --version              Show the release version.
  --help                 Show this help text.

The preflight rejects reusable discovery, OrthoFinder, expression, domain-result and
ligandability authorities. All scientific stages, including structural alignment, must be
enabled. Slurm mode submits the Snakemake controller as a batch job and is safe after logout.
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
        --threads)
            require_option_value "$1" "${2-}"
            THREADS="$2"
            shift 2
            ;;
        --max-jobs)
            require_option_value "$1" "${2-}"
            MAX_JOBS="$2"
            shift 2
            ;;
        --account)
            require_option_value "$1" "${2-}"
            ACCOUNT="$2"
            shift 2
            ;;
        --partition)
            require_option_value "$1" "${2-}"
            PARTITION="$2"
            shift 2
            ;;
        --resume)
            RESUME="true"
            shift
            ;;
        --status)
            STATUS_ONLY="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --version)
            printf 'E3 fresh pipeline launcher 0.9.0\n'
            exit 0
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS+=(-- "$@")
            break
            ;;
        *)
            EXTRA_ARGS+=("$1")
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
[[ "${MODE}" == "slurm" || "${MODE}" == "local" ]] || {
    printf 'ERROR: --mode must be slurm or local.\n' >&2
    exit 2
}
[[ "${THREADS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --threads must be a positive integer.\n' >&2
    exit 2
}
[[ "${MAX_JOBS}" =~ ^([1-9]|10)$ ]] || {
    printf 'ERROR: --max-jobs must be between 1 and 10 for the fresh launcher.\n' >&2
    exit 2
}
command -v e3-workflow >/dev/null || {
    printf 'ERROR: install e3_end_to_end_workflow before using this launcher.\n' >&2
    exit 2
}

CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"
declare -a PREFLIGHT_ARGS=(validate-fresh --config "${CONFIG}")
if [[ "${RESUME}" == "true" || "${STATUS_ONLY}" == "true" ]]; then
    PREFLIGHT_ARGS+=(--allow-existing-run)
fi
e3-workflow "${PREFLIGHT_ARGS[@]}" >/dev/null

declare -a LAUNCH_ARGS=(
    --config "${CONFIG}"
    --mode "${MODE}"
    --threads "${THREADS}"
    --max-jobs "${MAX_JOBS}"
    --account "${ACCOUNT}"
    --partition "${PARTITION}"
)
[[ "${RESUME}" == "false" ]] || LAUNCH_ARGS+=(--resume)
[[ "${STATUS_ONLY}" == "false" ]] || LAUNCH_ARGS+=(--status)
[[ "${DRY_RUN}" == "false" ]] || LAUNCH_ARGS+=(--dry-run)
LAUNCH_ARGS+=("${EXTRA_ARGS[@]}")
exec "${MASTER_LAUNCHER}" "${LAUNCH_ARGS[@]}"
