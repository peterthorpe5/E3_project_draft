#!/usr/bin/env bash
#SBATCH --job-name=e3_m2_validate
#SBATCH --account=barton
#SBATCH --partition=barton
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=e3_m2_validation.%j.log
#SBATCH --chdir=/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/E3_project_draft

# Install and validate the Milestone 2 packages on a Dundee compute node.

set -Eeuo pipefail

readonly EXPECTED_CHEMISTRY_VERSION="0.3.1"
readonly EXPECTED_WORKFLOW_VERSION="0.15.0"

REPOSITORY_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/E3_project_draft"
RUNS_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs"
WORKFLOW_ENVIRONMENT="e3_end_to_end_workflow"
CHEMISTRY_ENVIRONMENT="e3_structure_guided_chemistry"

usage() {
    printf '%s\n' \
        "Usage: sbatch validate_dundee_full_universe_v0_3_1.slurm.sh [options]" \
        "" \
        "Installs and fully validates both packages on a Slurm compute node." \
        "Successful validation is recorded against the exact Git commit." \
        "" \
        "Options:" \
        "  --repository-root PATH        E3_project_draft Git checkout." \
        "  --runs-root PATH              Workflow output root." \
        "  --workflow-environment NAME   End-to-end Conda environment." \
        "  --chemistry-environment NAME  Chemistry Conda environment." \
        "  --help                        Show this help."
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
        --repository-root|--runs-root|--workflow-environment|--chemistry-environment)
            require_value "$1" "${2:-}"
            case "$1" in
                --repository-root) REPOSITORY_ROOT="$2" ;;
                --runs-root) RUNS_ROOT="$2" ;;
                --workflow-environment) WORKFLOW_ENVIRONMENT="$2" ;;
                --chemistry-environment) CHEMISTRY_ENVIRONMENT="$2" ;;
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

if [[ ! -d "${REPOSITORY_ROOT}" ]]; then
    printf 'ERROR: repository root is unavailable: %s\n' \
        "${REPOSITORY_ROOT}" >&2
    exit 2
fi
REPOSITORY_ROOT="$(cd -- "${REPOSITORY_ROOT}" && pwd -P)"
readonly REPOSITORY_ROOT
readonly WORKFLOW_ROOT="${REPOSITORY_ROOT}/e3_end_to_end_workflow"
readonly CHEMISTRY_ROOT="${REPOSITORY_ROOT}/e3_structure_guided_chemistry"

for required_directory in "${WORKFLOW_ROOT}" "${CHEMISTRY_ROOT}"; do
    if [[ ! -d "${required_directory}" ]]; then
        printf 'ERROR: package directory is unavailable: %s\n' \
            "${required_directory}" >&2
        exit 2
    fi
done

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    printf 'ERROR: submit this validation shell with sbatch; do not run it on a login node.\n' >&2
    exit 2
fi
for required_command in conda git; do
    if ! command -v "${required_command}" >/dev/null 2>&1; then
        printf 'ERROR: required command is unavailable: %s\n' "${required_command}" >&2
        exit 2
    fi
done

assert_clean_package() {
    local package_path="$1"
    local untracked
    if ! git -C "${REPOSITORY_ROOT}" diff --quiet -- "${package_path}" || \
        ! git -C "${REPOSITORY_ROOT}" diff --cached --quiet -- "${package_path}"
    then
        printf 'ERROR: tracked source has uncommitted changes: %s\n' \
            "${package_path}" >&2
        return 2
    fi
    untracked="$(git -C "${REPOSITORY_ROOT}" ls-files \
        --others --exclude-standard -- "${package_path}")"
    if [[ -n "${untracked}" ]]; then
        printf 'ERROR: untracked source files are present in %s:\n%s\n' \
            "${package_path}" "${untracked}" >&2
        return 2
    fi
}

assert_clean_package "e3_end_to_end_workflow"
assert_clean_package "e3_structure_guided_chemistry"
SOURCE_COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
VALIDATION_DIR="${RUNS_ROOT}/software_validation"

printf 'Installing packages from Git commit %s on Slurm job %s.\n' \
    "${SOURCE_COMMIT}" "${SLURM_JOB_ID}"
conda run --no-capture-output --name "${WORKFLOW_ENVIRONMENT}" \
    python -m pip install --no-deps --editable "${WORKFLOW_ROOT}"
conda run --no-capture-output --name "${CHEMISTRY_ENVIRONMENT}" \
    python -m pip install --no-deps --editable "${CHEMISTRY_ROOT}"

validate_package() {
    local label="$1"
    local expected_version="$2"
    local environment_name="$3"
    local package_root="$4"
    local version_command="$5"
    local observed_version
    local partial
    local receipt="${VALIDATION_DIR}/${label}_${expected_version}_${SOURCE_COMMIT}.passed.tsv"

    observed_version="$(conda run --no-capture-output --name "${environment_name}" \
        bash -c "${version_command}")"
    observed_version="${observed_version##* }"
    if [[ "${observed_version}" != "${expected_version}" ]]; then
        printf 'ERROR: expected %s version %s but observed %s.\n' \
            "${label}" "${expected_version}" "${observed_version}" >&2
        return 2
    fi
    printf 'Running complete validation for %s %s.\n' \
        "${label}" "${expected_version}"
    conda run --no-capture-output --name "${environment_name}" \
        bash "${package_root}/run_tests.sh"
    mkdir -p -- "${VALIDATION_DIR}"
    partial="${receipt}.partial.${SLURM_JOB_ID}"
    printf 'package\tpackage_version\tgit_commit\tvalidated_at_utc\tslurm_job_id\n%s\t%s\t%s\t%s\t%s\n' \
        "${label}" "${expected_version}" "${SOURCE_COMMIT}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SLURM_JOB_ID}" >"${partial}"
    mv -- "${partial}" "${receipt}"
}

validate_package \
    "e3_end_to_end_workflow" "${EXPECTED_WORKFLOW_VERSION}" \
    "${WORKFLOW_ENVIRONMENT}" "${WORKFLOW_ROOT}" "e3-workflow --version"
validate_package \
    "e3_structure_guided_chemistry" "${EXPECTED_CHEMISTRY_VERSION}" \
    "${CHEMISTRY_ENVIRONMENT}" "${CHEMISTRY_ROOT}" "e3-chemistry --version"

printf 'Validation passed for both packages at Git commit %s.\n' "${SOURCE_COMMIT}"
printf 'Now run the lightweight orchestration shell from the login node.\n'
