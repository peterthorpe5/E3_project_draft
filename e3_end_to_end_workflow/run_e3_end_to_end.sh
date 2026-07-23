#!/usr/bin/env bash
# Run the master E3 Snakemake workflow through named, reusable options.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG="${SCRIPT_DIR}/config/synthetic.yaml"
PROFILE="local"
THREADS="4"
MAX_JOBS="50"
SLURM_ACCOUNT="barton"
SLURM_PARTITION="general"
TARGET=""
START_AT=""
STOP_AFTER=""
DRY_RUN="false"
UNLOCK="false"
RESUME="true"
ALLOW_INSIDE_SLURM="false"
declare -a FORCE_STAGES=()
declare -a EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: run_e3_end_to_end.sh [options] [-- additional Snakemake options]

Options:
  --config PATH          Workflow YAML (default: config/synthetic.yaml).
  --profile NAME         local, slurm, or an absolute profile directory.
  --threads INTEGER      Total local CPU budget (default: 4).
  --max-jobs INTEGER     Maximum concurrent Slurm jobs (default: 50).
  --account NAME         Slurm account for scientific jobs (default: barton).
  --partition NAME       Slurm partition for scientific jobs (default: general).
  --resume               Reuse only outputs Snakemake and stage manifests validate (default).
  --start-at STAGE       Intentionally rerun STAGE and affected downstream work.
  --stop-after STAGE     Stop once the selected stage manifest is complete.
  --force-stage STAGE    Intentionally rerun one stage; may be repeated.
  --target TARGET        Advanced explicit Snakemake target.
  --dry-run              Validate and print the DAG without executing jobs.
  --unlock               Unlock the configured working directory and exit.
  --allow-inside-slurm   Advanced override for an intentionally nested controller.
  --version              Show the package version and exit.
  --help                 Show this help text.

Use submit_e3_end_to_end.sh for normal detached cluster execution. This foreground runner always
launches the package Snakefile. Independent branches run concurrently when dependencies and
resources permit. --start-at never bypasses missing prerequisites.
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
        --resume)
            RESUME="true"
            shift
            ;;
        --start-at)
            require_option_value "$1" "${2-}"
            START_AT="$2"
            shift 2
            ;;
        --stop-after)
            require_option_value "$1" "${2-}"
            STOP_AFTER="$2"
            shift 2
            ;;
        --force-stage)
            require_option_value "$1" "${2-}"
            FORCE_STAGES+=("$2")
            shift 2
            ;;
        --target)
            require_option_value "$1" "${2-}"
            TARGET="$2"
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
        --allow-inside-slurm)
            ALLOW_INSIDE_SLURM="true"
            shift
            ;;
        --version)
            printf 'e3-end-to-end-workflow 0.7.0\n'
            exit 0
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

[[ -f "${CONFIG}" ]] || {
    printf 'ERROR: config not found: %s\n' "${CONFIG}" >&2
    exit 2
}
[[ "${THREADS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --threads must be positive.\n' >&2
    exit 2
}
[[ "${MAX_JOBS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --max-jobs must be positive.\n' >&2
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
    printf 'ERROR: install this package first: python -m pip install -e %s\n' \
        "${SCRIPT_DIR}" >&2
    exit 2
}
command -v snakemake >/dev/null || {
    printf 'ERROR: snakemake is not on PATH.\n' >&2
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

if [[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/slurm" && -n "${SLURM_JOB_ID:-}" && \
        "${ALLOW_INSIDE_SLURM}" == "false" ]]; then
    printf 'ERROR: refusing to launch the Snakemake Slurm controller inside Slurm job %s.\n' \
        "${SLURM_JOB_ID}" >&2
    printf 'Use submit_e3_end_to_end.sh from a login node for detached execution.\n' >&2
    exit 2
fi

declare -ar STAGES=(
    00_inputs
    01_prepared_proteomes
    02_discovery
    03_candidate_evidence
    04_orthofinder
    05_orthology
    06_domains
    07_expression
    08_shortlist_gate
    09_ligandability
    09b_structural_alignment
    10_integrated_resource
    11_app_ready
)

stage_index() {
    local requested="$1"
    local index
    for index in "${!STAGES[@]}"; do
        if [[ "${STAGES[${index}]}" == "${requested}" ]]; then
            printf '%s\n' "${index}"
            return 0
        fi
    done
    printf 'ERROR: unknown stage: %s\n' "${requested}" >&2
    return 2
}

[[ -z "${START_AT}" ]] || stage_index "${START_AT}" >/dev/null
[[ -z "${STOP_AFTER}" ]] || stage_index "${STOP_AFTER}" >/dev/null
for stage_name in "${FORCE_STAGES[@]}"; do
    stage_index "${stage_name}" >/dev/null
done
if [[ -n "${START_AT}" && -n "${STOP_AFTER}" ]]; then
    e3-workflow validate-range --start-at "${START_AT}" --stop-after "${STOP_AFTER}" \
        >/dev/null
fi
if [[ -n "${TARGET}" && -n "${STOP_AFTER}" ]]; then
    printf 'ERROR: --target and --stop-after are mutually exclusive.\n' >&2
    exit 2
fi
if [[ "${DRY_RUN}" == "true" && ( -n "${START_AT}" || ${#FORCE_STAGES[@]} -gt 0 ) ]]; then
    printf 'ERROR: --dry-run cannot refresh --start-at or --force-stage control tokens.\n' >&2
    exit 2
fi

export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${TMPDIR:-/tmp}/e3_workflow_cache_${UID}}"
mkdir -p -- "${XDG_CACHE_HOME}"

e3-workflow validate --config "${CONFIG}" >/dev/null
CONTROL_ARGS=(control --config "${CONFIG}")
[[ -n "${START_AT}" ]] && CONTROL_ARGS+=(--force-stage "${START_AT}")
for stage_name in "${FORCE_STAGES[@]}"; do
    [[ "${stage_name}" == "${START_AT}" ]] || CONTROL_ARGS+=(--force-stage "${stage_name}")
done
e3-workflow "${CONTROL_ARGS[@]}" >/dev/null

FINAL_TARGET="$(
    e3-workflow stage-target --config "${CONFIG}" --stage "${STAGES[-1]}"
)"
RUN_ROOT="$(dirname -- "$(dirname -- "${FINAL_TARGET}")")"
mkdir -p "${RUN_ROOT}/workflow_logs"
LOG="${RUN_ROOT}/workflow_logs/controller_$(date -u '+%Y%m%dT%H%M%SZ').log"
exec > >(tee -a "${LOG}") 2>&1
printf '%s INFO Configuration: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CONFIG}"
printf '%s INFO Profile: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${PROFILE}"
printf '%s INFO Resume policy: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${RESUME}"
printf '%s INFO Maximum concurrent Slurm jobs: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${MAX_JOBS}"
printf '%s INFO Local CPU budget: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${THREADS}"
if [[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/slurm" ]]; then
    printf '%s INFO Slurm account: %s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_ACCOUNT}"
    printf '%s INFO Slurm partition: %s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_PARTITION}"
fi
[[ -z "${START_AT}" ]] || printf '%s INFO Start at: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${START_AT}"
[[ -z "${STOP_AFTER}" ]] || printf '%s INFO Stop after: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${STOP_AFTER}"
printf '%s INFO The plan below explains what every stage does and why.\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
e3-workflow validate --config "${CONFIG}"
e3-workflow plan --config "${CONFIG}" --human

if [[ -n "${STOP_AFTER}" ]]; then
    TARGET="$(e3-workflow stage-target --config "${CONFIG}" --stage "${STOP_AFTER}")"
fi

COMMAND=(
    snakemake
    --snakefile "${SCRIPT_DIR}/workflow/Snakefile"
    --configfile "${CONFIG}"
    --profile "${PROFILE}"
    --rerun-incomplete
    --printshellcmds
    --show-failed-logs
)
if [[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/local" ]]; then
    COMMAND+=(--cores "${THREADS}")
fi
if [[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/slurm" ]]; then
    COMMAND+=(
        --jobs "${MAX_JOBS}"
        --default-resources
        "slurm_account=${SLURM_ACCOUNT}"
        "slurm_partition=${SLURM_PARTITION}"
        "mem_mb=8000"
        "runtime=60"
    )
fi
[[ "${DRY_RUN}" == "true" ]] && COMMAND+=(--dry-run)
[[ "${UNLOCK}" == "true" ]] && COMMAND+=(--unlock)
[[ -n "${TARGET}" ]] && COMMAND+=("${TARGET}")
COMMAND+=("${EXTRA_ARGS[@]}")
printf 'Command:'
printf ' %q' "${COMMAND[@]}"
printf '\n'
if [[ "${UNLOCK}" == "false" ]]; then
    e3-workflow record-invocation --config "${CONFIG}" -- "${COMMAND[@]}" >/dev/null
    printf '%s INFO Recorded the exact shell-to-Snakemake command for HTML provenance.\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
fi
"${COMMAND[@]}"

if [[ "${DRY_RUN}" == "false" && "${UNLOCK}" == "false" ]]; then
    printf '%s INFO Workflow command completed successfully.\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    FULL_DAG_COMPLETION="true"
    [[ -z "${TARGET}" ]] || FULL_DAG_COMPLETION="false"
    for extra_argument in "${EXTRA_ARGS[@]}"; do
        case "${extra_argument}" in
            --nolock|--keep-going) ;;
            *) FULL_DAG_COMPLETION="false" ;;
        esac
    done
    if [[ "${FULL_DAG_COMPLETION}" == "true" ]]; then
        POSTPROCESSING_OUTPUTS=(
            "${RUN_ROOT}/benchmark_summary/benchmark_manifest.json"
            "${RUN_ROOT}/benchmark_summary/stage_resource_summary.tsv"
            "${RUN_ROOT}/benchmark_summary/workflow_resource_summary.tsv"
            "${RUN_ROOT}/benchmark_summary/slurm_accounting_status.tsv"
            "${RUN_ROOT}/benchmark_summary/slurm_accounting.tsv"
            "${RUN_ROOT}/benchmark_summary/benchmark_complete.tsv"
            "${RUN_ROOT}/reports/e3_workflow_summary.html"
            "${RUN_ROOT}/reports/report_manifest.json"
            "${RUN_ROOT}/reports/report_complete.tsv"
        )
        for stage_name in "${STAGES[@]}"; do
            POSTPROCESSING_OUTPUTS+=(
                "${RUN_ROOT}/${stage_name}/stage_manifest.json"
                "${RUN_ROOT}/${stage_name}/report/stage_report.html"
            )
        done
        CLEANUP_LOG="$(mktemp "${TMPDIR:-/tmp}/e3_workflow_metadata.XXXXXX.log")"
        CLEANUP_COMMAND=(
            snakemake
            --snakefile "${SCRIPT_DIR}/workflow/Snakefile"
            --configfile "${CONFIG}"
            --cleanup-metadata
            "${POSTPROCESSING_OUTPUTS[@]}"
        )
        CLEANUP_RESULT=""
        for cleanup_attempt in 1 2 3; do
            if "${CLEANUP_COMMAND[@]}" >"${CLEANUP_LOG}" 2>&1; then
                CLEANUP_RESULT="metadata_removed"
                break
            elif grep -Fq "metadata was not present" "${CLEANUP_LOG}" && \
                    ! grep -Eq "Traceback|OSError|PermissionError" "${CLEANUP_LOG}"; then
                CLEANUP_RESULT="markers_removed"
                if [[ "${cleanup_attempt}" -lt 3 ]]; then
                    sleep 1
                    continue
                fi
                break
            else
                printf 'ERROR: completed-output metadata cleanup failed.\n' >&2
                sed -n '1,240p' "${CLEANUP_LOG}" >&2
                rm -f -- "${CLEANUP_LOG}"
                exit 1
            fi
        done
        if [[ "${CLEANUP_RESULT}" == "metadata_removed" ]]; then
            printf '%s INFO Cleared completed-output metadata.\n' \
                "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        else
            printf '%s INFO Cleared completed-output incomplete markers after a bounded '\
'filesystem-latency retry; completed-job metadata was already absent as required.\n' \
                "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        fi
        rm -f -- "${CLEANUP_LOG}"
    fi
    printf '%s INFO Successful-job metadata was dropped by the Snakemake profile; checksummed '\
'stage manifests and control tokens remain the restart authority.\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
fi
