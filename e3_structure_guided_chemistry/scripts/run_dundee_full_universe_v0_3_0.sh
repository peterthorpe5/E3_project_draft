#!/usr/bin/env bash
# Validate and run the staged Dundee full-universe structural/chemistry campaign.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly CHEMISTRY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPOSITORY_ROOT="$(cd -- "${CHEMISTRY_ROOT}/.." && pwd -P)"
readonly WORKFLOW_ROOT="${REPOSITORY_ROOT}/e3_end_to_end_workflow"
readonly EXPECTED_CHEMISTRY_VERSION="0.3.0"
readonly EXPECTED_WORKFLOW_VERSION="0.14.1"

RUNS_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs"
PARENT_RUN_ROOT="${RUNS_ROOT}/grant_aligned_corrected_expression_structural_top200_v0_14_0_20260805"
FULL_RUN_NAME="grant_aligned_corrected_expression_structural_all1972_v0_15_0_20260811"
FULL_RUN_ROOT="${RUNS_ROOT}/${FULL_RUN_NAME}"
WORKFLOW_TEMPLATE="${WORKFLOW_ROOT}/config/grant_aligned_structural_sensitivity_top100_v0_11_0_20260729.cluster.yaml"
GENERATED_CONFIG="${RUNS_ROOT}/workflow_configs/${FULL_RUN_NAME}.yaml"
CHEMISTRY_CONFIG="${CHEMISTRY_ROOT}/config/full_universe_prepare_only_v0_3_0.yaml"
PANEL_DIR="${RUNS_ROOT}/milestone2_candidate_panel_full_universe_v0_3_0_20260811"
OUTPUT_DIR="${RUNS_ROOT}/milestone2_open_chemistry_full_universe_v0_3_0_20260811"
DECIDED_BY="Peter Thorpe"
STRUCTURE_GROUP_LIMIT="1972"
WORKFLOW_ENVIRONMENT="e3_end_to_end_workflow"
CHEMISTRY_ENVIRONMENT="e3_structure_guided_chemistry"
ACCOUNT="barton"
PARTITION="barton"
CONTROLLER_QOS="4week"
CONTROLLER_RUNTIME="28-00:00:00"
MAX_JOBS="200"
CHEMISTRY_WALLTIME="2-00:00:00"
CHEMISTRY_MEMORY="64G"
CHEMISTRY_CPUS="4"

usage() {
    printf '%s\n' \
        "Usage: run_dundee_full_universe_v0_3_0.sh [options]" \
        "" \
        "One restart-safe command for the 1,972-group upstream structural campaign" \
        "and the subsequent v0.3.0 chemistry assessment. Re-run the same command" \
        "after the controller finishes; completed work is never resubmitted." \
        "" \
        "Optional overrides:" \
        "  --runs-root PATH              Workflow output root." \
        "  --parent-run-root PATH        Corrected-expression parent run." \
        "  --full-run-name NAME          New immutable structural run name." \
        "  --workflow-template PATH      Reviewed upstream template YAML." \
        "  --generated-config PATH       Generated immutable workflow YAML." \
        "  --chemistry-config PATH       Reviewed v0.3.0 chemistry YAML." \
        "  --panel-dir PATH              Full-universe candidate-panel directory." \
        "  --output-dir PATH             Chemistry output directory." \
        "  --decided-by TEXT             Screen authoriser." \
        "  --structure-group-limit INT   Stage 08 groups sent upstream (default: 1972)." \
        "  --workflow-environment NAME   End-to-end Conda environment." \
        "  --chemistry-environment NAME  Chemistry Conda environment." \
        "  --account NAME                Slurm account." \
        "  --partition NAME              Slurm partition." \
        "  --controller-qos NAME         Long controller QoS (default: 4week)." \
        "  --without-controller-qos      Do not request a controller QoS." \
        "  --controller-runtime TIME     Controller walltime." \
        "  --max-jobs INT                Maximum concurrent child jobs." \
        "  --chemistry-walltime TIME     Chemistry allocation walltime." \
        "  --chemistry-memory SIZE       Chemistry allocation memory." \
        "  --chemistry-cpus INT          Chemistry allocation CPUs." \
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
        --runs-root|--parent-run-root|--full-run-name|--workflow-template|--generated-config|--chemistry-config|--panel-dir|--output-dir|--decided-by|--structure-group-limit|--workflow-environment|--chemistry-environment|--account|--partition|--controller-qos|--controller-runtime|--max-jobs|--chemistry-walltime|--chemistry-memory|--chemistry-cpus)
            require_value "$1" "${2:-}"
            case "$1" in
                --runs-root) RUNS_ROOT="$2" ;;
                --parent-run-root) PARENT_RUN_ROOT="$2" ;;
                --full-run-name) FULL_RUN_NAME="$2" ;;
                --workflow-template) WORKFLOW_TEMPLATE="$2" ;;
                --generated-config) GENERATED_CONFIG="$2" ;;
                --chemistry-config) CHEMISTRY_CONFIG="$2" ;;
                --panel-dir) PANEL_DIR="$2" ;;
                --output-dir) OUTPUT_DIR="$2" ;;
                --decided-by) DECIDED_BY="$2" ;;
                --structure-group-limit) STRUCTURE_GROUP_LIMIT="$2" ;;
                --workflow-environment) WORKFLOW_ENVIRONMENT="$2" ;;
                --chemistry-environment) CHEMISTRY_ENVIRONMENT="$2" ;;
                --account) ACCOUNT="$2" ;;
                --partition) PARTITION="$2" ;;
                --controller-qos) CONTROLLER_QOS="$2" ;;
                --controller-runtime) CONTROLLER_RUNTIME="$2" ;;
                --max-jobs) MAX_JOBS="$2" ;;
                --chemistry-walltime) CHEMISTRY_WALLTIME="$2" ;;
                --chemistry-memory) CHEMISTRY_MEMORY="$2" ;;
                --chemistry-cpus) CHEMISTRY_CPUS="$2" ;;
            esac
            shift 2
            ;;
        --without-controller-qos)
            CONTROLLER_QOS=""
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

FULL_RUN_ROOT="${RUNS_ROOT}/${FULL_RUN_NAME}"
for integer_setting in STRUCTURE_GROUP_LIMIT MAX_JOBS CHEMISTRY_CPUS; do
    value="${!integer_setting}"
    if [[ ! "${value}" =~ ^[1-9][0-9]*$ ]]; then
        printf 'ERROR: %s must be a positive integer.\n' "${integer_setting}" >&2
        exit 2
    fi
done
for required_command in conda git sbatch squeue timeout; do
    if ! command -v "${required_command}" >/dev/null 2>&1; then
        printf 'ERROR: required command is unavailable: %s\n' \
            "${required_command}" >&2
        exit 2
    fi
done
for required_path in \
    "${PARENT_RUN_ROOT}" \
    "${WORKFLOW_ROOT}" \
    "${CHEMISTRY_ROOT}"
do
    if [[ ! -d "${required_path}" ]]; then
        printf 'ERROR: required directory is unavailable: %s\n' \
            "${required_path}" >&2
        exit 2
    fi
done
for required_file in "${WORKFLOW_TEMPLATE}" "${CHEMISTRY_CONFIG}"; do
    if [[ ! -s "${required_file}" ]]; then
        printf 'ERROR: required configuration is unavailable: %s\n' \
            "${required_file}" >&2
        exit 2
    fi
done

assert_clean_package() {
    local package_path="$1"
    local untracked
    if ! git -C "${REPOSITORY_ROOT}" diff --quiet -- "${package_path}"; then
        printf 'ERROR: tracked source has unstaged changes: %s\n' \
            "${package_path}" >&2
        return 2
    fi
    if ! git -C "${REPOSITORY_ROOT}" diff --cached --quiet -- "${package_path}"; then
        printf 'ERROR: tracked source has staged, uncommitted changes: %s\n' \
            "${package_path}" >&2
        return 2
    fi
    untracked="$(
        git -C "${REPOSITORY_ROOT}" ls-files \
            --others \
            --exclude-standard \
            -- "${package_path}"
    )"
    if [[ -n "${untracked}" ]]; then
        printf 'ERROR: untracked source files are present in %s:\n%s\n' \
            "${package_path}" "${untracked}" >&2
        return 2
    fi
}

printf 'Checking tracked workflow and chemistry source.\n'
assert_clean_package "e3_end_to_end_workflow"
assert_clean_package "e3_structure_guided_chemistry"
SOURCE_COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"

printf 'Refreshing editable package installations.\n'
conda run \
    --no-capture-output \
    --name "${WORKFLOW_ENVIRONMENT}" \
    python -m pip install --no-deps --editable "${WORKFLOW_ROOT}"
conda run \
    --no-capture-output \
    --name "${CHEMISTRY_ENVIRONMENT}" \
    python -m pip install --no-deps --editable "${CHEMISTRY_ROOT}"

WORKFLOW_VERSION="$(
    conda run \
        --no-capture-output \
        --name "${WORKFLOW_ENVIRONMENT}" \
        e3-workflow --version
)"
WORKFLOW_VERSION="${WORKFLOW_VERSION##* }"
CHEMISTRY_VERSION="$(
    conda run \
        --no-capture-output \
        --name "${CHEMISTRY_ENVIRONMENT}" \
        e3-chemistry --version
)"
if [[ "${WORKFLOW_VERSION}" != "${EXPECTED_WORKFLOW_VERSION}" ]]; then
    printf 'ERROR: expected workflow package %s but observed %s.\n' \
        "${EXPECTED_WORKFLOW_VERSION}" "${WORKFLOW_VERSION}" >&2
    exit 2
fi
if [[ "${CHEMISTRY_VERSION}" != "${EXPECTED_CHEMISTRY_VERSION}" ]]; then
    printf 'ERROR: expected chemistry package %s but observed %s.\n' \
        "${EXPECTED_CHEMISTRY_VERSION}" "${CHEMISTRY_VERSION}" >&2
    exit 2
fi

VALIDATION_DIR="${RUNS_ROOT}/software_validation"
validate_package() {
    local label="$1"
    local version="$2"
    local environment_name="$3"
    local package_root="$4"
    local receipt="${VALIDATION_DIR}/${label}_${version}_${SOURCE_COMMIT}.passed.tsv"
    local partial
    if [[ -s "${receipt}" ]]; then
        printf 'Validation already passed for %s at Git commit %s.\n' \
            "${label}" "${SOURCE_COMMIT}"
        return 0
    fi
    printf 'Running complete validation for %s at Git commit %s.\n' \
        "${label}" "${SOURCE_COMMIT}"
    conda run \
        --no-capture-output \
        --name "${environment_name}" \
        bash "${package_root}/run_tests.sh"
    mkdir -p -- "${VALIDATION_DIR}"
    partial="${receipt}.partial"
    printf 'package\tpackage_version\tgit_commit\tvalidated_at_utc\n%s\t%s\t%s\t%s\n' \
        "${label}" \
        "${version}" \
        "${SOURCE_COMMIT}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${partial}"
    mv -- "${partial}" "${receipt}"
}

validate_package \
    "e3_end_to_end_workflow" \
    "${EXPECTED_WORKFLOW_VERSION}" \
    "${WORKFLOW_ENVIRONMENT}" \
    "${WORKFLOW_ROOT}"
validate_package \
    "e3_structure_guided_chemistry" \
    "${EXPECTED_CHEMISTRY_VERSION}" \
    "${CHEMISTRY_ENVIRONMENT}" \
    "${CHEMISTRY_ROOT}"

printf 'Generating or verifying the immutable 1,972-group workflow configuration.\n'
conda run \
    --no-capture-output \
    --name "${CHEMISTRY_ENVIRONMENT}" \
    e3-chemistry prepare-full-universe-workflow-config \
    --template "${WORKFLOW_TEMPLATE}" \
    --output "${GENERATED_CONFIG}" \
    --run-name "${FULL_RUN_NAME}" \
    --parent-run-root "${PARENT_RUN_ROOT}" \
    --structure-group-limit "${STRUCTURE_GROUP_LIMIT}"

manifest_is_complete() {
    local manifest_path="$1"
    [[ -s "${manifest_path}" ]] && \
        grep -Eq '"status"[[:space:]]*:[[:space:]]*"complete"' \
            "${manifest_path}"
}

APP_READY_MANIFEST="${FULL_RUN_ROOT}/11_app_ready/stage_manifest.json"
CONTROLLER_METADATA="${FULL_RUN_ROOT}/workflow_control/controller.slurm.tsv"
CONTROLLER_LAUNCHER="${WORKFLOW_ROOT}/submit_e3_controller_slurm.sh"
if ! manifest_is_complete "${APP_READY_MANIFEST}"; then
    if [[ -s "${CONTROLLER_METADATA}" ]]; then
        CONTROLLER_STATUS="$(
            "${CONTROLLER_LAUNCHER}" \
                --config "${GENERATED_CONFIG}" \
                --conda-environment "${WORKFLOW_ENVIRONMENT}" \
                --status
        )"
        printf '%s\n' "${CONTROLLER_STATUS}"
        if grep -Eq '^Controller: (PENDING|RUNNING|CONFIGURING|COMPLETING|REQUEUED|REQUEUE_FED|REQUEUE_HOLD|RESIZING|RESV_DEL_HOLD|SIGNALING|STAGE_OUT|STOPPED|SUSPENDED)$' \
            <<<"${CONTROLLER_STATUS}"
        then
            printf 'The full structural campaign is active. Re-run this same command after it completes.\n'
            exit 0
        fi
        if grep -Eq '^Controller: (STATUS_QUERY_FAILED|METADATA_INVALID)$' \
            <<<"${CONTROLLER_STATUS}"
        then
            printf 'ERROR: controller state is not safe to interpret; no submission was attempted.\n' >&2
            exit 2
        fi
    fi

    printf 'Submitting or safely resuming the full structural campaign.\n'
    QOS_ARGS=()
    if [[ -n "${CONTROLLER_QOS}" ]]; then
        QOS_ARGS=(--controller-qos "${CONTROLLER_QOS}")
    fi
    "${CONTROLLER_LAUNCHER}" \
        --config "${GENERATED_CONFIG}" \
        --controller-account "${ACCOUNT}" \
        --controller-partition "${PARTITION}" \
        --controller-runtime "${CONTROLLER_RUNTIME}" \
        "${QOS_ARGS[@]}" \
        --conda-environment "${WORKFLOW_ENVIRONMENT}" \
        --account "${ACCOUNT}" \
        --partition "${PARTITION}" \
        --max-jobs "${MAX_JOBS}" \
        --resume
    printf 'Upstream work was submitted. Re-run this same command after the controller completes; chemistry is intentionally not submitted yet.\n'
    exit 0
fi

printf 'The full upstream structural campaign is complete. Preparing chemistry inputs.\n'
PANEL_MANIFEST="${PANEL_DIR}/candidate_manifest.tsv"
PANEL_EXCLUSIONS="${PANEL_DIR}/candidate_manifest_exclusions.tsv"
PANEL_PROVENANCE="${PANEL_DIR}/candidate_manifest_provenance.json"
PANEL_AUDIT="${PANEL_DIR}/candidate_universe_audit.tsv"
if [[ -s "${PANEL_MANIFEST}" && -s "${PANEL_EXCLUSIONS}" && \
    -s "${PANEL_PROVENANCE}" && -s "${PANEL_AUDIT}" ]]
then
    printf 'Full-universe candidate panel is already complete; skipping preparation.\n'
elif [[ -e "${PANEL_DIR}" ]]; then
    printf 'ERROR: candidate-panel directory exists but is incomplete: %s\n' \
        "${PANEL_DIR}" >&2
    exit 2
else
    "${SCRIPT_DIR}/prepare_expanded_candidate_manifest.sh" \
        --run-root "${FULL_RUN_ROOT}" \
        --config "${CHEMISTRY_CONFIG}" \
        --output-dir "${PANEL_DIR}" \
        --all-ranked-groups \
        --decided-by "${DECIDED_BY}" \
        --conda-environment "${CHEMISTRY_ENVIRONMENT}"
fi

INCLUDED_COUNT="$(awk 'END {print NR > 0 ? NR - 1 : 0}' "${PANEL_MANIFEST}")"
EXCLUDED_COUNT="$(awk 'END {print NR > 0 ? NR - 1 : 0}' "${PANEL_EXCLUSIONS}")"
printf 'Full universe: %s structurally eligible groups included; %s explicitly excluded.\n' \
    "${INCLUDED_COUNT}" "${EXCLUDED_COUNT}"

RUN_MANIFEST="${OUTPUT_DIR}/provenance/run_manifest.json"
SUBMISSION_RECEIPT="${OUTPUT_DIR}.submission.tsv"
if [[ -s "${RUN_MANIFEST}" ]]; then
    printf 'Full-universe chemistry analysis is complete: %s\n' "${OUTPUT_DIR}"
    exit 0
fi
if [[ -s "${SUBMISSION_RECEIPT}" ]]; then
    printf 'Chemistry was already submitted; no duplicate job was created.\n'
    cat -- "${SUBMISSION_RECEIPT}"
    exit 0
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
    printf 'ERROR: chemistry output exists without a completion manifest or submission receipt: %s\n' \
        "${OUTPUT_DIR}" >&2
    exit 2
fi

printf 'Submitting the full-universe open chemistry analysis.\n'
"${SCRIPT_DIR}/submit_e3_structure_guided_chemistry_slurm.sh" \
    --run-root "${FULL_RUN_ROOT}" \
    --config "${CHEMISTRY_CONFIG}" \
    --candidate-manifest "${PANEL_MANIFEST}" \
    --output-dir "${OUTPUT_DIR}" \
    --account "${ACCOUNT}" \
    --partition "${PARTITION}" \
    --walltime "${CHEMISTRY_WALLTIME}" \
    --memory "${CHEMISTRY_MEMORY}" \
    --cpus "${CHEMISTRY_CPUS}" \
    --conda-environment "${CHEMISTRY_ENVIRONMENT}" \
    --job-id-file "${SUBMISSION_RECEIPT}"

printf 'The full-universe chemistry job is now submitted.\n'
