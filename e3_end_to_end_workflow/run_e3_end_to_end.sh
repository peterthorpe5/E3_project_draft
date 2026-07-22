#!/usr/bin/env bash
# Run the master E3 Snakemake workflow through named, reusable options.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG="${SCRIPT_DIR}/config/synthetic.yaml"
PROFILE="local"
THREADS="4"
MAX_JOBS="50"
TARGET=""
START_AT=""
STOP_AFTER=""
DRY_RUN="false"
UNLOCK="false"
RESUME="true"
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
  --resume               Reuse only outputs Snakemake and stage manifests validate (default).
  --start-at STAGE       Intentionally rerun STAGE and affected downstream work.
  --stop-after STAGE     Stop once the selected stage manifest is complete.
  --force-stage STAGE    Intentionally rerun one stage; may be repeated.
  --target TARGET        Advanced explicit Snakemake target.
  --dry-run              Validate and print the DAG without executing jobs.
  --unlock               Unlock the configured working directory and exit.
  --version              Show the package version and exit.
  --help                 Show this help text.

The shell wrapper always launches the package Snakefile. Independent branches run concurrently
when dependencies and resources permit. --start-at never bypasses missing prerequisites.
EOF
}

while (($#)); do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --threads|--cores) THREADS="$2"; shift 2 ;;
        --max-jobs|--jobs) MAX_JOBS="$2"; shift 2 ;;
        --resume) RESUME="true"; shift ;;
        --start-at) START_AT="$2"; shift 2 ;;
        --stop-after) STOP_AFTER="$2"; shift 2 ;;
        --force-stage) FORCE_STAGES+=("$2"); shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --dry-run) DRY_RUN="true"; shift ;;
        --unlock) UNLOCK="true"; shift ;;
        --version) printf 'e3-end-to-end-workflow 0.3.0\n'; exit 0 ;;
        --help|-h) usage; exit 0 ;;
        --) shift; EXTRA_ARGS+=("$@"); break ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -f "${CONFIG}" ]] || { printf 'ERROR: config not found: %s\n' "${CONFIG}" >&2; exit 2; }
[[ "${THREADS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --threads must be positive.\n' >&2
    exit 2
}
[[ "${MAX_JOBS}" =~ ^[1-9][0-9]*$ ]] || {
    printf 'ERROR: --max-jobs must be positive.\n' >&2
    exit 2
}
command -v e3-workflow >/dev/null || {
    printf 'ERROR: install this package first: python -m pip install -e %s\n' "${SCRIPT_DIR}" >&2
    exit 2
}
command -v snakemake >/dev/null || { printf 'ERROR: snakemake is not on PATH.\n' >&2; exit 2; }

CONFIG="$(python -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "${CONFIG}")"
if [[ "${PROFILE}" != /* ]]; then
    PROFILE="${SCRIPT_DIR}/profiles/${PROFILE}"
fi
[[ -d "${PROFILE}" ]] || { printf 'ERROR: profile not found: %s\n' "${PROFILE}" >&2; exit 2; }

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

COMMAND=(snakemake --snakefile "${SCRIPT_DIR}/workflow/Snakefile" --configfile "${CONFIG}"
    --profile "${PROFILE}" --rerun-incomplete --printshellcmds --show-failed-logs)
[[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/local" ]] && COMMAND+=(--cores "${THREADS}")
[[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/slurm" ]] && COMMAND+=(--jobs "${MAX_JOBS}")
[[ "${DRY_RUN}" == "true" ]] && COMMAND+=(--dry-run)
[[ "${UNLOCK}" == "true" ]] && COMMAND+=(--unlock)
[[ -n "${TARGET}" ]] && COMMAND+=("${TARGET}")
COMMAND+=("${EXTRA_ARGS[@]}")
printf 'Command:'; printf ' %q' "${COMMAND[@]}"; printf '\n'
"${COMMAND[@]}"
