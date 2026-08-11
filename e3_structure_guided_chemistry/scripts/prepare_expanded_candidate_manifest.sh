#!/usr/bin/env bash
# Prepare a checksum-bound expanded Stage 08/09 candidate panel.

set -Eeuo pipefail

RUN_ROOT=""
CONFIG=""
OUTPUT_DIR=""
DECIDED_BY=""
MAXIMUM_RANK="200"
CONDA_ENVIRONMENT="e3_structure_guided_chemistry"
RATIONALE="Expanded computational screen of the completed Stage 08 top-200 authority using quality-first mapped-pocket selection; not project-lead approval."

usage() {
    printf '%s\n' \
        "Usage: prepare_expanded_candidate_manifest.sh [options]" \
        "" \
        "Required:" \
        "  --run-root PATH          Completed workflow run through Stage 09." \
        "  --config PATH            Reviewed v0.2.x chemistry YAML." \
        "  --output-dir PATH        New candidate-manifest directory." \
        "  --decided-by TEXT        Person authorising the expanded screen." \
        "" \
        "Optional:" \
        "  --maximum-rank INTEGER   Maximum Stage 08 rank (default: 200)." \
        "  --rationale TEXT         Decision rationale stored in every row." \
        "  --conda-environment NAME Environment name." \
        "  --help                   Show this help."
}

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
        --run-root|--config|--output-dir|--decided-by|--maximum-rank|--rationale|--conda-environment)
            require_value "$1" "${2:-}"
            case "$1" in
                --run-root) RUN_ROOT="$2" ;;
                --config) CONFIG="$2" ;;
                --output-dir) OUTPUT_DIR="$2" ;;
                --decided-by) DECIDED_BY="$2" ;;
                --maximum-rank) MAXIMUM_RANK="$2" ;;
                --rationale) RATIONALE="$2" ;;
                --conda-environment) CONDA_ENVIRONMENT="$2" ;;
            esac
            shift 2
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

if [[ -z "${RUN_ROOT}" || -z "${CONFIG}" || -z "${OUTPUT_DIR}" || -z "${DECIDED_BY}" ]]; then
    printf 'ERROR: --run-root, --config, --output-dir and --decided-by are required.\n' >&2
    exit 2
fi
if [[ ! "${MAXIMUM_RANK}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: --maximum-rank must be a positive integer.\n' >&2
    exit 2
fi
if [[ ! -d "${RUN_ROOT}" ]]; then
    printf 'ERROR: run root is not a directory: %s\n' "${RUN_ROOT}" >&2
    exit 2
fi
if [[ ! -s "${CONFIG}" ]]; then
    printf 'ERROR: chemistry config is missing or empty: %s\n' "${CONFIG}" >&2
    exit 2
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
    printf 'ERROR: output already exists: %s\n' "${OUTPUT_DIR}" >&2
    exit 2
fi
if ! command -v conda >/dev/null 2>&1; then
    printf 'ERROR: conda is unavailable.\n' >&2
    exit 2
fi

readonly GROUP_RANKING="${RUN_ROOT}/08_shortlist_gate/tables/evolutionary_candidate_group_ranking.parquet"
readonly STAGE09_TABLES="${RUN_ROOT}/09_ligandability/tables"
readonly SELECTED_POCKETS="${STAGE09_TABLES}/selected_pockets.parquet"
readonly POCKET_MAPPINGS="${STAGE09_TABLES}/reused_pocket_residue_mappings.parquet"
readonly ASSET_MANIFEST="${STAGE09_TABLES}/reused_asset_manifest.parquet"

for required_file in \
    "${GROUP_RANKING}" \
    "${SELECTED_POCKETS}" \
    "${POCKET_MAPPINGS}" \
    "${ASSET_MANIFEST}"
do
    if [[ ! -s "${required_file}" ]]; then
        printf 'ERROR: required workflow authority is missing: %s\n' \
            "${required_file}" >&2
        exit 2
    fi
done

conda run \
    --no-capture-output \
    --name "${CONDA_ENVIRONMENT}" \
    e3-chemistry prepare-candidate-manifest \
    --config "${CONFIG}" \
    --group-ranking "${GROUP_RANKING}" \
    --selected-pockets "${SELECTED_POCKETS}" \
    --pocket-residue-mappings "${POCKET_MAPPINGS}" \
    --structure-asset-manifest "${ASSET_MANIFEST}" \
    --output-dir "${OUTPUT_DIR}" \
    --maximum-rank "${MAXIMUM_RANK}" \
    --decision-basis EXPANDED_COMPUTATIONAL_SCREEN \
    --decided-by "${DECIDED_BY}" \
    --rationale "${RATIONALE}"
