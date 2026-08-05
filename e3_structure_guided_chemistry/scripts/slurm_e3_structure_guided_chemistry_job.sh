#!/usr/bin/env bash
# Slurm worker for the standalone open-source chemistry hand-off.

set -Eeuo pipefail

PACKAGE_ROOT=""
CONDA_ENVIRONMENT="e3_structure_guided_chemistry"
declare -a RUN_ARGUMENTS=()

require_value() {
    local option_name="$1"
    local option_value="${2:-}"
    if [[ -z "${option_value}" || "${option_value}" == --* ]]; then
        printf 'ERROR: %s requires a value.\n' "${option_name}" >&2
        exit 2
    fi
}

while (($#)); do
    case "$1" in
        --package-root)
            require_value "$1" "${2:-}"
            PACKAGE_ROOT="$2"
            shift 2
            ;;
        --conda-environment)
            require_value "$1" "${2:-}"
            CONDA_ENVIRONMENT="$2"
            shift 2
            ;;
        --config|--group-ranking|--selected-pockets|--pocket-residue-mappings|--pocket-conservation-summary|--structure-asset-manifest|--output-dir)
            require_value "$1" "${2:-}"
            RUN_ARGUMENTS+=("$1" "$2")
            shift 2
            ;;
        *)
            printf 'ERROR: unknown worker option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "${PACKAGE_ROOT}" ]]; then
    printf 'ERROR: worker requires --package-root.\n' >&2
    exit 2
fi
if [[ ! -x "${PACKAGE_ROOT}/run_e3_structure_guided_chemistry.sh" ]]; then
    printf 'ERROR: chemistry runner is missing or not executable: %s\n' \
        "${PACKAGE_ROOT}/run_e3_structure_guided_chemistry.sh" >&2
    exit 2
fi
if ! command -v conda >/dev/null 2>&1; then
    printf 'ERROR: conda is unavailable in the Slurm job environment.\n' >&2
    exit 2
fi

printf 'Starting open-source E3 chemistry at %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
conda run \
    --no-capture-output \
    --name "${CONDA_ENVIRONMENT}" \
    "${PACKAGE_ROOT}/run_e3_structure_guided_chemistry.sh" \
    "${RUN_ARGUMENTS[@]}"
printf 'Finished open-source E3 chemistry at %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
