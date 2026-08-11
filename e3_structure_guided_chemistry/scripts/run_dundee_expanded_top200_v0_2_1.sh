#!/usr/bin/env bash
# Validate, prepare and submit the Dundee expanded top-200 chemistry run.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PACKAGE_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPOSITORY_ROOT="$(cd -- "${PACKAGE_ROOT}/.." && pwd -P)"
readonly EXPECTED_VERSION="0.2.1"

RUNS_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs"
RUN_ROOT="${RUNS_ROOT}/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"
PANEL_DIR="${RUNS_ROOT}/milestone2_candidate_panel_expanded_top200_v0_2_1_20260811"
OUTPUT_DIR="${RUNS_ROOT}/milestone2_open_chemistry_expanded_top200_v0_2_1_20260811"
CONFIG="${PACKAGE_ROOT}/config/expanded_top200_prepare_only_v0_2_1.yaml"
DECIDED_BY="Peter Thorpe"
MAXIMUM_RANK="200"
CONDA_ENVIRONMENT="e3_structure_guided_chemistry"
ACCOUNT="barton"
PARTITION="barton"
WALLTIME="12:00:00"
MEMORY="16G"
CPUS="4"

usage() {
    printf '%s\n' \
        "Usage: run_dundee_expanded_top200_v0_2_1.sh [options]" \
        "" \
        "Runs the complete checked Dundee v0.2.1 preparation and submission." \
        "All project paths and Slurm settings have production defaults." \
        "" \
        "Optional overrides:" \
        "  --run-root PATH          Completed Stage 08/09 workflow run." \
        "  --panel-dir PATH         Candidate-panel output directory." \
        "  --output-dir PATH        Chemistry analysis output directory." \
        "  --config PATH            Reviewed chemistry YAML." \
        "  --decided-by TEXT        Screen authoriser." \
        "  --maximum-rank INTEGER   Maximum Stage 08 rank." \
        "  --conda-environment NAME Conda environment name." \
        "  --account NAME           Slurm account." \
        "  --partition NAME         Slurm partition." \
        "  --walltime TIME          Slurm walltime." \
        "  --memory SIZE            Slurm memory." \
        "  --cpus INTEGER           Slurm CPUs." \
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
        --run-root|--panel-dir|--output-dir|--config|--decided-by|--maximum-rank|--conda-environment|--account|--partition|--walltime|--memory|--cpus)
            require_value "$1" "${2:-}"
            case "$1" in
                --run-root) RUN_ROOT="$2" ;;
                --panel-dir) PANEL_DIR="$2" ;;
                --output-dir) OUTPUT_DIR="$2" ;;
                --config) CONFIG="$2" ;;
                --decided-by) DECIDED_BY="$2" ;;
                --maximum-rank) MAXIMUM_RANK="$2" ;;
                --conda-environment) CONDA_ENVIRONMENT="$2" ;;
                --account) ACCOUNT="$2" ;;
                --partition) PARTITION="$2" ;;
                --walltime) WALLTIME="$2" ;;
                --memory) MEMORY="$2" ;;
                --cpus) CPUS="$2" ;;
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

if [[ ! "${MAXIMUM_RANK}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: --maximum-rank must be a positive integer.\n' >&2
    exit 2
fi
if [[ ! "${CPUS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: --cpus must be a positive integer.\n' >&2
    exit 2
fi
for command_name in conda git sbatch; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'ERROR: required command is unavailable: %s\n' \
            "${command_name}" >&2
        exit 2
    fi
done
if [[ ! -d "${RUN_ROOT}" ]]; then
    printf 'ERROR: workflow run root is unavailable: %s\n' "${RUN_ROOT}" >&2
    exit 2
fi
if [[ ! -s "${CONFIG}" ]]; then
    printf 'ERROR: chemistry configuration is unavailable: %s\n' "${CONFIG}" >&2
    exit 2
fi

printf 'Checking tracked package source.\n'
if ! git -C "${REPOSITORY_ROOT}" diff --quiet -- e3_structure_guided_chemistry; then
    printf 'ERROR: tracked chemistry source has unstaged changes.\n' >&2
    exit 2
fi
if ! git -C "${REPOSITORY_ROOT}" diff --cached --quiet -- e3_structure_guided_chemistry; then
    printf 'ERROR: tracked chemistry source has staged, uncommitted changes.\n' >&2
    exit 2
fi
UNTRACKED_SOURCE="$(
    git -C "${REPOSITORY_ROOT}" ls-files \
        --others \
        --exclude-standard \
        -- e3_structure_guided_chemistry
)"
if [[ -n "${UNTRACKED_SOURCE}" ]]; then
    printf 'ERROR: untracked chemistry source files are present:\n%s\n' \
        "${UNTRACKED_SOURCE}" >&2
    exit 2
fi
SOURCE_COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"

printf 'Refreshing editable package installation.\n'
conda run \
    --no-capture-output \
    --name "${CONDA_ENVIRONMENT}" \
    python -m pip install \
        --no-deps \
        --editable "${PACKAGE_ROOT}"

INSTALLED_VERSION="$(
    conda run \
        --no-capture-output \
        --name "${CONDA_ENVIRONMENT}" \
        e3-chemistry --version
)"
if [[ "${INSTALLED_VERSION}" != "${EXPECTED_VERSION}" ]]; then
    printf 'ERROR: expected package %s but observed %s.\n' \
        "${EXPECTED_VERSION}" "${INSTALLED_VERSION}" >&2
    exit 2
fi

VALIDATION_DIR="${RUNS_ROOT}/software_validation"
VALIDATION_RECEIPT="${VALIDATION_DIR}/e3_structure_guided_chemistry_${EXPECTED_VERSION}_${SOURCE_COMMIT}.passed.tsv"
if [[ -s "${VALIDATION_RECEIPT}" ]]; then
    printf 'Validation already passed for Git commit %s; skipping tests.\n' \
        "${SOURCE_COMMIT}"
else
    printf 'Running complete package validation for Git commit %s.\n' \
        "${SOURCE_COMMIT}"
    conda run \
        --no-capture-output \
        --name "${CONDA_ENVIRONMENT}" \
        bash "${PACKAGE_ROOT}/run_tests.sh"
    mkdir -p -- "${VALIDATION_DIR}"
    VALIDATION_PARTIAL="${VALIDATION_RECEIPT}.partial"
    printf 'package_version\tgit_commit\tvalidated_at_utc\n%s\t%s\t%s\n' \
        "${EXPECTED_VERSION}" \
        "${SOURCE_COMMIT}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${VALIDATION_PARTIAL}"
    mv -- "${VALIDATION_PARTIAL}" "${VALIDATION_RECEIPT}"
fi

printf 'Validating production configuration.\n'
conda run \
    --no-capture-output \
    --name "${CONDA_ENVIRONMENT}" \
    e3-chemistry validate-config \
    --config "${CONFIG}"

PANEL_MANIFEST="${PANEL_DIR}/candidate_manifest.tsv"
PANEL_EXCLUSIONS="${PANEL_DIR}/candidate_manifest_exclusions.tsv"
PANEL_PROVENANCE="${PANEL_DIR}/candidate_manifest_provenance.json"
if [[ -s "${PANEL_MANIFEST}" && -s "${PANEL_EXCLUSIONS}" && -s "${PANEL_PROVENANCE}" ]]; then
    printf 'Candidate panel is already complete; skipping preparation.\n'
elif [[ -e "${PANEL_DIR}" ]]; then
    printf 'ERROR: candidate-panel directory exists but is incomplete: %s\n' \
        "${PANEL_DIR}" >&2
    exit 2
else
    printf 'Preparing checksum-bound expanded candidate panel.\n'
    "${SCRIPT_DIR}/prepare_expanded_candidate_manifest.sh" \
        --run-root "${RUN_ROOT}" \
        --config "${CONFIG}" \
        --output-dir "${PANEL_DIR}" \
        --maximum-rank "${MAXIMUM_RANK}" \
        --decided-by "${DECIDED_BY}" \
        --conda-environment "${CONDA_ENVIRONMENT}"
fi

INCLUDED_COUNT="$(awk 'END {print NR - 1}' "${PANEL_MANIFEST}")"
EXCLUDED_COUNT="$(awk 'END {print NR - 1}' "${PANEL_EXCLUSIONS}")"
printf 'Candidate panel: %s included groups; %s excluded groups.\n' \
    "${INCLUDED_COUNT}" "${EXCLUDED_COUNT}"

RUN_MANIFEST="${OUTPUT_DIR}/provenance/run_manifest.json"
SUBMISSION_RECEIPT="${OUTPUT_DIR}.submission.tsv"
if [[ -s "${RUN_MANIFEST}" ]]; then
    printf 'Expanded chemistry analysis is already complete: %s\n' \
        "${OUTPUT_DIR}"
    exit 0
fi
if [[ -s "${SUBMISSION_RECEIPT}" ]]; then
    printf 'Analysis was already submitted; no duplicate job was created.\n'
    cat -- "${SUBMISSION_RECEIPT}"
    printf 'Expected Slurm log pattern: %s.slurm.JOB_ID.log\n' "${OUTPUT_DIR}"
    exit 0
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
    printf 'ERROR: analysis output exists without a completion manifest or submission receipt: %s\n' \
        "${OUTPUT_DIR}" >&2
    exit 2
fi

printf 'Submitting expanded chemistry analysis to Slurm.\n'
"${SCRIPT_DIR}/submit_e3_structure_guided_chemistry_slurm.sh" \
    --run-root "${RUN_ROOT}" \
    --config "${CONFIG}" \
    --candidate-manifest "${PANEL_MANIFEST}" \
    --output-dir "${OUTPUT_DIR}" \
    --account "${ACCOUNT}" \
    --partition "${PARTITION}" \
    --walltime "${WALLTIME}" \
    --memory "${MEMORY}" \
    --cpus "${CPUS}" \
    --conda-environment "${CONDA_ENVIRONMENT}" \
    --job-id-file "${SUBMISSION_RECEIPT}"

printf 'The checked expanded top-200 workflow is now submitted.\n'
