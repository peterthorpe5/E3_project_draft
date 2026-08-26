#!/usr/bin/env bash
# Run the restartable human-and-plant extension against a completed plant release.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG=""
PROFILE="slurm"
THREADS="8"
MAX_JOBS="50"
SLURM_ACCOUNT="barton"
SLURM_PARTITION="general"
DRY_RUN="false"
UNLOCK="false"
declare -a EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: run_human_plant_structural_extension.sh --config PATH [options]

Required:
  --config PATH          Human-and-plant extension YAML.

Execution:
  --profile NAME         local, slurm, or an absolute profile (default: slurm).
  --threads INTEGER      Local CPU budget (default: 8).
  --max-jobs INTEGER     Concurrent scientific Slurm jobs (default: 50).
  --account NAME         Slurm account (default: barton).
  --partition NAME       Slurm partition (default: general).
  --dry-run              Validate and show the extension DAG only.
  --unlock               Unlock this extension working directory and exit.
  --help                 Show this help text.
  --                     Forward remaining arguments directly to Snakemake.

This workflow reads a completed plant release, runs only the missing human
AlphaFold/FPocket/P2Rank work, preserves each plant structural reference, and
publishes a separate app-ready human-and-plant pocket-review bundle. Existing
plant outputs are never modified.
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
            PROFILE="$2"
            shift 2
            ;;
        --threads|--cores)
            require_option_value "$1" "${2-}"
            THREADS="$2"
            shift 2
            ;;
        --max-jobs|--jobs)
            require_option_value "$1" "${2-}"
            MAX_JOBS="$2"
            shift 2
            ;;
        --account)
            require_option_value "$1" "${2-}"
            SLURM_ACCOUNT="$2"
            shift 2
            ;;
        --partition)
            require_option_value "$1" "${2-}"
            SLURM_PARTITION="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --unlock)
            UNLOCK="true"
            shift
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
            usage >&2
            exit 2
            ;;
    esac
done

[[ -n "${CONFIG}" ]] || {
    printf 'ERROR: --config is required.\n' >&2
    exit 2
}
[[ -f "${CONFIG}" ]] || {
    printf 'ERROR: config not found: %s\n' "${CONFIG}" >&2
    exit 2
}
[[ "${THREADS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --threads must be a positive integer.\n' >&2
    exit 2
}
[[ "${MAX_JOBS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --max-jobs must be a positive integer.\n' >&2
    exit 2
}
[[ "${SLURM_ACCOUNT}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf 'ERROR: --account contains unsafe characters.\n' >&2
    exit 2
}
[[ "${SLURM_PARTITION}" =~ ^[A-Za-z0-9._-]+$ ]] || {
    printf 'ERROR: --partition contains unsafe characters.\n' >&2
    exit 2
}
command -v e3-workflow >/dev/null || {
    printf 'ERROR: e3-workflow is not installed in the active environment.\n' >&2
    exit 2
}
command -v snakemake >/dev/null || {
    printf 'ERROR: snakemake is not installed in the active environment.\n' >&2
    exit 2
}

CONFIG_DIRECTORY="$(cd -- "$(dirname -- "${CONFIG}")" && pwd -P)"
CONFIG="${CONFIG_DIRECTORY}/$(basename -- "${CONFIG}")"
if [[ "${PROFILE}" != /* ]]; then
    PROFILE="${SCRIPT_DIR}/profiles/${PROFILE}"
fi
[[ -d "${PROFILE}" ]] || {
    printf 'ERROR: profile not found: %s\n' "${PROFILE}" >&2
    exit 2
}
PROFILE="$(cd -- "${PROFILE}" && pwd -P)"

COMMAND=(
    snakemake
    --snakefile "${SCRIPT_DIR}/workflow/HumanPlantExtension.smk"
    --configfile "${CONFIG}"
    --profile "${PROFILE}"
    --rerun-incomplete
    --printshellcmds
    --show-failed-logs
)
if [[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/local" ]]; then
    COMMAND+=(--cores "${THREADS}")
else
    COMMAND+=(
        --jobs "${MAX_JOBS}"
        --default-resources
        "slurm_account=${SLURM_ACCOUNT}"
        "slurm_partition=${SLURM_PARTITION}"
        "mem_mb=8000"
        "runtime=60"
    )
fi
[[ "${DRY_RUN}" == "false" ]] || COMMAND+=(--dry-run)
[[ "${UNLOCK}" == "false" ]] || COMMAND+=(--unlock)
COMMAND+=("${EXTRA_ARGS[@]}")

printf 'Command:'
printf ' %q' "${COMMAND[@]}"
printf '\n'
exec "${COMMAND[@]}"
