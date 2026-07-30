#!/usr/bin/env bash
# Submit a bounded ARIA E3 pocket-review report build to Slurm.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly JOB_SCRIPT="${SCRIPT_DIR}/slurm_e3_pocket_review_job.sh"

RUN_ROOT=""
OUTPUT_DIR=""
ACCOUNT="barton"
PARTITION="barton"
WALLTIME="04:00:00"
MEMORY="16G"
CPUS="4"
CONDA_ENVIRONMENT="e3_structural_alignment"
REVIEW_LIMIT="50"
MEMBER_POCKET_TOP_K="5"
RESUME="false"

usage() {
    printf '%s\n' \
        "Usage: submit_e3_pocket_review_slurm.sh --run-root PATH --output-dir PATH [options]" \
        "" \
        "Options:" \
        "  --account NAME                 Slurm account (default: barton)." \
        "  --partition NAME               Slurm partition (default: barton)." \
        "  --walltime TIME                Slurm time, never above five days." \
        "  --memory SIZE                  Slurm memory (default: 16G)." \
        "  --cpus INTEGER                 CPU count (default: 4)." \
        "  --conda-environment NAME       Conda environment name." \
        "  --review-limit INTEGER         Ranked groups to report (default: 50)." \
        "  --member-pocket-top-k INTEGER  Pocket ranks to display (default: 5)." \
        "  --resume                       Reuse a matching completed report." \
        "  --help                         Show this help."
}

require_value() {
    local option_name="$1"
    local option_value="${2:-}"
    if [[ -z "${option_value}" ]]; then
        printf 'ERROR: %s requires a value.\n' "${option_name}" >&2
        exit 2
    fi
}

positive_integer() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

validate_walltime() {
    local value="$1"
    if [[ "${value}" =~ ^([0-9]+)-([0-9]{2}):([0-9]{2}):([0-9]{2})$ ]]; then
        local days=$((10#${BASH_REMATCH[1]}))
        local hours=$((10#${BASH_REMATCH[2]}))
        local minutes=$((10#${BASH_REMATCH[3]}))
        local seconds=$((10#${BASH_REMATCH[4]}))
        (( hours <= 23 && minutes <= 59 && seconds <= 59 )) || return 1
        if (( days < 5 )); then
            return 0
        fi
        if (( days == 5 && hours == 0 && minutes == 0 && seconds == 0 )); then
            return 0
        fi
        return 1
    fi
    if [[ "${value}" =~ ^([0-9]{1,3}):([0-9]{2}):([0-9]{2})$ ]]; then
        (( 10#${BASH_REMATCH[1]} <= 120 )) || return 1
        (( 10#${BASH_REMATCH[2]} <= 59 )) || return 1
        (( 10#${BASH_REMATCH[3]} <= 59 )) || return 1
        return 0
    fi
    return 1
}

while (($#)); do
    case "$1" in
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
        --account)
            require_value "$1" "${2:-}"
            ACCOUNT="$2"
            shift 2
            ;;
        --partition)
            require_value "$1" "${2:-}"
            PARTITION="$2"
            shift 2
            ;;
        --walltime)
            require_value "$1" "${2:-}"
            WALLTIME="$2"
            shift 2
            ;;
        --memory)
            require_value "$1" "${2:-}"
            MEMORY="$2"
            shift 2
            ;;
        --cpus)
            require_value "$1" "${2:-}"
            CPUS="$2"
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
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf 'ERROR: unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "${RUN_ROOT}" || -z "${OUTPUT_DIR}" ]]; then
    printf 'ERROR: --run-root and --output-dir are required.\n' >&2
    exit 2
fi
if [[ ! -d "${RUN_ROOT}" ]]; then
    printf 'ERROR: run root is not a directory: %s\n' "${RUN_ROOT}" >&2
    exit 2
fi
if ! positive_integer "${CPUS}" || ! positive_integer "${REVIEW_LIMIT}" ||
    ! positive_integer "${MEMBER_POCKET_TOP_K}"; then
    printf 'ERROR: CPU, review-limit and top-k values must be positive integers.\n' >&2
    exit 2
fi
if ! validate_walltime "${WALLTIME}"; then
    printf 'ERROR: walltime must be valid and no longer than five days: %s\n' \
        "${WALLTIME}" >&2
    exit 2
fi
if ! command -v sbatch >/dev/null 2>&1; then
    printf 'ERROR: sbatch is unavailable; submit this command from a Slurm login node.\n' >&2
    exit 2
fi

mkdir -p -- "$(dirname -- "${OUTPUT_DIR}")"

JOB_ARGUMENTS=(
    --run-root "${RUN_ROOT}"
    --output-dir "${OUTPUT_DIR}"
    --conda-environment "${CONDA_ENVIRONMENT}"
    --review-limit "${REVIEW_LIMIT}"
    --member-pocket-top-k "${MEMBER_POCKET_TOP_K}"
)
if [[ "${RESUME}" == "true" ]]; then
    JOB_ARGUMENTS+=(--resume)
fi

JOB_ID="$(
    sbatch \
        --parsable \
        --job-name="e3_pocket_review" \
        --account="${ACCOUNT}" \
        --partition="${PARTITION}" \
        --time="${WALLTIME}" \
        --mem="${MEMORY}" \
        --cpus-per-task="${CPUS}" \
        --output="${OUTPUT_DIR}.slurm.%j.log" \
        --error="${OUTPUT_DIR}.slurm.%j.log" \
        "${JOB_SCRIPT}" \
        "${JOB_ARGUMENTS[@]}"
)"
printf 'Submitted E3 pocket-review report job: %s\n' "${JOB_ID}"
printf 'Slurm log: %s\n' "${OUTPUT_DIR}.slurm.${JOB_ID}.log"
