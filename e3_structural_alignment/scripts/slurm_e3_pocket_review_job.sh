#!/usr/bin/env bash
# Slurm worker for one self-contained E3 pocket-review report build.

set -Eeuo pipefail

PACKAGE_ROOT=""
RUN_ROOT=""
OUTPUT_DIR=""
CONDA_ENVIRONMENT="e3_structural_alignment"
REVIEW_LIMIT="50"
MEMBER_POCKET_TOP_K="5"
RESUME="false"

require_value() {
    local option_name="$1"
    local option_value="${2:-}"
    if [[ -z "${option_value}" ]]; then
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
        --run-root)
            require_value "$1" "${2:-}"
            RUN_ROOT="$2"
            shift 2
            ;;
        --output-dir)
            require_value "$1" "${2:-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --conda-environment)
            require_value "$1" "${2:-}"
            CONDA_ENVIRONMENT="$2"
            shift 2
            ;;
        --review-limit)
            require_value "$1" "${2:-}"
            REVIEW_LIMIT="$2"
            shift 2
            ;;
        --member-pocket-top-k)
            require_value "$1" "${2:-}"
            MEMBER_POCKET_TOP_K="$2"
            shift 2
            ;;
        --resume)
            RESUME="true"
            shift
            ;;
        *)
            printf 'ERROR: unknown worker option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "${PACKAGE_ROOT}" || -z "${RUN_ROOT}" || -z "${OUTPUT_DIR}" ]]; then
    printf '%s\n' \
        'ERROR: worker requires --package-root, --run-root and --output-dir.' >&2
    exit 2
fi
if [[ ! -d "${PACKAGE_ROOT}" ]]; then
    printf 'ERROR: package root is not a directory: %s\n' "${PACKAGE_ROOT}" >&2
    exit 2
fi
if [[ ! -f "${PACKAGE_ROOT}/run_e3_pocket_review.sh" ]]; then
    printf 'ERROR: pocket-review runner is missing: %s\n' \
        "${PACKAGE_ROOT}/run_e3_pocket_review.sh" >&2
    exit 2
fi
if ! command -v conda >/dev/null 2>&1; then
    printf 'ERROR: conda executable is unavailable in the Slurm job environment.\n' >&2
    exit 2
fi

COMMAND=(
    conda run --name "${CONDA_ENVIRONMENT}"
    bash "${PACKAGE_ROOT}/run_e3_pocket_review.sh"
    --run-root "${RUN_ROOT}"
    --output-dir "${OUTPUT_DIR}"
    --review-limit "${REVIEW_LIMIT}"
    --member-pocket-top-k "${MEMBER_POCKET_TOP_K}"
    --verbose
)
if [[ "${RESUME}" == "true" ]]; then
    COMMAND+=(--resume)
fi

printf 'Starting E3 pocket-review report at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'Run root: %s\nOutput directory: %s\n' "${RUN_ROOT}" "${OUTPUT_DIR}"
"${COMMAND[@]}"
printf 'Finished E3 pocket-review report at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
