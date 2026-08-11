#!/usr/bin/env bash
# Submit one standalone open-source chemistry hand-off to Slurm.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PACKAGE_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly JOB_SCRIPT="${SCRIPT_DIR}/slurm_e3_structure_guided_chemistry_job.sh"

RUN_ROOT=""
CONFIG=""
CANDIDATE_MANIFEST=""
OUTPUT_DIR=""
ACCOUNT="barton"
PARTITION="barton"
WALLTIME="12:00:00"
MEMORY="16G"
CPUS="4"
CONDA_ENVIRONMENT="e3_structure_guided_chemistry"
JOB_ID_FILE=""

usage() {
    printf '%s\n' \
        "Usage: submit_e3_structure_guided_chemistry_slurm.sh [options]" \
        "" \
        "Required:" \
        "  --run-root PATH          Completed workflow run through Stage 09." \
        "  --config PATH            Reviewed chemistry component YAML." \
        "  --candidate-manifest PATH Explicit reviewed candidate panel TSV." \
        "  --output-dir PATH        New standalone output directory." \
        "" \
        "Slurm options:" \
        "  --account NAME           Account (default: barton)." \
        "  --partition NAME         Partition (default: barton)." \
        "  --walltime TIME          Walltime (default: 12:00:00)." \
        "  --memory SIZE            Memory (default: 16G)." \
        "  --cpus INTEGER           CPUs (default: 4)." \
        "  --conda-environment NAME Environment name." \
        "  --job-id-file PATH       New TSV submission receipt." \
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
        --run-root|--config|--candidate-manifest|--output-dir|--account|--partition|--walltime|--memory|--cpus|--conda-environment|--job-id-file)
            require_value "$1" "${2:-}"
            case "$1" in
                --run-root) RUN_ROOT="$2" ;;
                --config) CONFIG="$2" ;;
                --candidate-manifest) CANDIDATE_MANIFEST="$2" ;;
                --output-dir) OUTPUT_DIR="$2" ;;
                --account) ACCOUNT="$2" ;;
                --partition) PARTITION="$2" ;;
                --walltime) WALLTIME="$2" ;;
                --memory) MEMORY="$2" ;;
                --cpus) CPUS="$2" ;;
                --conda-environment) CONDA_ENVIRONMENT="$2" ;;
                --job-id-file) JOB_ID_FILE="$2" ;;
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

if [[ -z "${RUN_ROOT}" || -z "${CONFIG}" || -z "${CANDIDATE_MANIFEST}" || -z "${OUTPUT_DIR}" ]]; then
    printf 'ERROR: --run-root, --config, --candidate-manifest and --output-dir are required.\n' >&2
    exit 2
fi
if [[ ! -d "${RUN_ROOT}" ]]; then
    printf 'ERROR: run root is not a directory: %s\n' "${RUN_ROOT}" >&2
    exit 2
fi
if [[ ! -s "${CONFIG}" ]]; then
    printf 'ERROR: component config is missing or empty: %s\n' "${CONFIG}" >&2
    exit 2
fi
if [[ ! -s "${CANDIDATE_MANIFEST}" ]]; then
    printf 'ERROR: candidate manifest is missing or empty: %s\n' \
        "${CANDIDATE_MANIFEST}" >&2
    exit 2
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
    printf 'ERROR: output already exists: %s\n' "${OUTPUT_DIR}" >&2
    exit 2
fi
if [[ -n "${JOB_ID_FILE}" && -e "${JOB_ID_FILE}" ]]; then
    printf 'ERROR: job-ID receipt already exists: %s\n' "${JOB_ID_FILE}" >&2
    exit 2
fi
if [[ ! "${CPUS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: --cpus must be a positive integer.\n' >&2
    exit 2
fi
if ! command -v sbatch >/dev/null 2>&1; then
    printf 'ERROR: sbatch is unavailable; submit from a Slurm login node.\n' >&2
    exit 2
fi

readonly GROUP_RANKING="${RUN_ROOT}/08_shortlist_gate/tables/evolutionary_candidate_group_ranking.parquet"
readonly STAGE09_TABLES="${RUN_ROOT}/09_ligandability/tables"
readonly SELECTED_POCKETS="${STAGE09_TABLES}/selected_pockets.parquet"
readonly POCKET_MAPPINGS="${STAGE09_TABLES}/reused_pocket_residue_mappings.parquet"
readonly CONSERVATION="${STAGE09_TABLES}/pocket_conservation_summary.parquet"
readonly ASSET_MANIFEST="${STAGE09_TABLES}/reused_asset_manifest.parquet"

for required_file in \
    "${GROUP_RANKING}" \
    "${SELECTED_POCKETS}" \
    "${POCKET_MAPPINGS}" \
    "${CONSERVATION}" \
    "${ASSET_MANIFEST}"
do
    if [[ ! -s "${required_file}" ]]; then
        printf 'ERROR: required workflow authority is missing: %s\n' \
            "${required_file}" >&2
        exit 2
    fi
done

mkdir -p -- "$(dirname -- "${OUTPUT_DIR}")"
JOB_ID="$(
    sbatch \
        --parsable \
        --job-name=e3_open_chemistry \
        --account="${ACCOUNT}" \
        --partition="${PARTITION}" \
        --time="${WALLTIME}" \
        --mem="${MEMORY}" \
        --cpus-per-task="${CPUS}" \
        --output="${OUTPUT_DIR}.slurm.%j.log" \
        --error="${OUTPUT_DIR}.slurm.%j.log" \
        "${JOB_SCRIPT}" \
        --package-root "${PACKAGE_ROOT}" \
        --conda-environment "${CONDA_ENVIRONMENT}" \
        --config "${CONFIG}" \
        --candidate-manifest "${CANDIDATE_MANIFEST}" \
        --group-ranking "${GROUP_RANKING}" \
        --selected-pockets "${SELECTED_POCKETS}" \
        --pocket-residue-mappings "${POCKET_MAPPINGS}" \
        --pocket-conservation-summary "${CONSERVATION}" \
        --structure-asset-manifest "${ASSET_MANIFEST}" \
        --output-dir "${OUTPUT_DIR}"
)"

if [[ -n "${JOB_ID_FILE}" ]]; then
    mkdir -p -- "$(dirname -- "${JOB_ID_FILE}")"
    RECEIPT_PARTIAL="${JOB_ID_FILE}.partial"
    printf 'job_id\tsubmitted_at_utc\toutput_dir\n%s\t%s\t%s\n' \
        "${JOB_ID}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "${OUTPUT_DIR}" > "${RECEIPT_PARTIAL}"
    mv -- "${RECEIPT_PARTIAL}" "${JOB_ID_FILE}"
fi

printf 'Submitted open-source E3 chemistry job: %s\n' "${JOB_ID}"
printf 'Slurm log: %s\n' "${OUTPUT_DIR}.slurm.${JOB_ID}.log"
