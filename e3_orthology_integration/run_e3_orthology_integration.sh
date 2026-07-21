#!/usr/bin/env bash
# Run the complete staged orthology integration through one named-option interface.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONDA_ENV="e3_orthology"
WRAPPER_LOG=""
RESOLVE_RUN_ROOT_ONLY="false"
declare -a CLI_ARGS=()

usage() {
    cat <<'EOF'
Usage:
  run_e3_orthology_integration.sh [wrapper options] [pipeline named options]

Wrapper options:
  --conda-env NAME       Conda environment containing the installed package.
  --wrapper-log PATH     Shell-level log; default: RUN_ROOT/logs/wrapper_<timestamp>.log.
  --help                 Show this help and the Python pipeline help.

Core pipeline options:
  --project-root PATH
  --data-dir PATH
  --orthofinder-source-root PATH | --orthofinder-results-dir PATH
  --candidate-evidence PATH
  --sqlite-database PATH
  --species-manifest PATH
  --output-root PATH
  --run-name NAME
  --config PATH
  --results-directory-name NAME
  --expected-species-count INTEGER
  --regression-accession ACCESSION
  --expected-raw-identifier IDENTIFIER
  --expected-orthogroup IDENTIFIER
  --expected-hierarchical-orthogroup IDENTIFIER
  --skip-sqlite-regression
  --threads INTEGER
  --resume
  --start-at STAGE
  --stop-after STAGE
  --force-stage STAGE       Repeat for multiple stages.
  --dry-run
  --verbose

The Results_Feb26 cluster paths and scientific regressions are built-in defaults.
All pipeline arguments are named; no source file is edited to change a run.
EOF
}

while (($#)); do
    case "$1" in
        --conda-env)
            [[ $# -ge 2 ]] || { printf 'ERROR: --conda-env requires a value.\n' >&2; exit 2; }
            CONDA_ENV="$2"
            shift 2
            ;;
        --wrapper-log)
            [[ $# -ge 2 ]] || { printf 'ERROR: --wrapper-log requires a value.\n' >&2; exit 2; }
            WRAPPER_LOG="$2"
            shift 2
            ;;
        --resolve-run-root)
            RESOLVE_RUN_ROOT_ONLY="true"
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            CLI_ARGS+=("$1")
            shift
            ;;
    esac
done

command -v conda >/dev/null 2>&1 || {
    printf 'ERROR: conda is not available on PATH.\n' >&2
    exit 2
}

resolve_run_root() {
    local run_root

    if ! run_root="$(
        conda run --no-capture-output -n "${CONDA_ENV}" \
            python -m e3orthology --print-run-root "${CLI_ARGS[@]}"
    )"; then
        printf 'ERROR: could not resolve the pipeline run directory.\n' >&2
        return 2
    fi
    if [[ -z "${run_root}" || "${run_root}" != /* || "${run_root}" == *$'\n'* ]]; then
        printf 'ERROR: resolved run directory is not one absolute path: %q\n' \
            "${run_root}" >&2
        return 2
    fi
    printf '%s\n' "${run_root}"
}

RUN_ROOT="$(resolve_run_root)"
if [[ "${RESOLVE_RUN_ROOT_ONLY}" == "true" ]]; then
    printf '%s\n' "${RUN_ROOT}"
    exit 0
fi

if [[ -z "${WRAPPER_LOG}" ]]; then
    TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
    WRAPPER_LOG="${RUN_ROOT}/logs/wrapper_${TIMESTAMP}.log"
fi
mkdir -p -- "$(dirname -- "${WRAPPER_LOG}")"
exec > >(tee -a -- "${WRAPPER_LOG}") 2>&1

on_error() {
    local exit_code=$?
    printf '%s\tERROR\tWrapper failed at line %s with exit code %s.\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${BASH_LINENO[0]}" "${exit_code}"
    exit "${exit_code}"
}
trap on_error ERR

printf '%s\tINFO\tWrapper started.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf '%s\tINFO\tPackage directory: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SCRIPT_DIR}"
printf '%s\tINFO\tConda environment: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CONDA_ENV}"
printf '%s\tINFO\tRun directory: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${RUN_ROOT}"
printf '%s\tINFO\tWrapper log: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${WRAPPER_LOG}"
conda env list | awk 'NF && $1 !~ /^#/{print $1}' | grep -Fx -- "${CONDA_ENV}" >/dev/null || {
    printf 'ERROR: conda environment does not exist: %s\n' "${CONDA_ENV}" >&2
    exit 2
}

conda run --no-capture-output -n "${CONDA_ENV}" \
    python -m e3orthology "${CLI_ARGS[@]}"

printf '%s\tINFO\tWrapper completed successfully.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
