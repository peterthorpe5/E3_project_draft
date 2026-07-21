#!/usr/bin/env bash
# Run the master E3 Snakemake workflow through named, reusable options.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG="${SCRIPT_DIR}/config/synthetic.yaml"
PROFILE="local"
CORES="4"
JOBS="50"
TARGET=""
DRY_RUN="false"
UNLOCK="false"
declare -a EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: run_e3_end_to_end.sh [options] [-- additional Snakemake options]

Options:
  --config PATH       Workflow YAML (default: config/synthetic.yaml).
  --profile NAME      local, slurm, or an absolute profile directory.
  --cores INTEGER     Local cores (default: 4).
  --jobs INTEGER      Maximum submitted Slurm jobs (default: 50).
  --target TARGET     Optional Snakemake target or stage manifest.
  --dry-run           Validate and print the DAG without executing jobs.
  --unlock            Unlock the configured working directory and exit.
  --help              Show this help text.

The wrapper always enables rerun-incomplete, shell-command printing and failed-log display.
EOF
}

while (($#)); do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --cores) CORES="$2"; shift 2 ;;
        --jobs) JOBS="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --dry-run) DRY_RUN="true"; shift ;;
        --unlock) UNLOCK="true"; shift ;;
        --help|-h) usage; exit 0 ;;
        --) shift; EXTRA_ARGS+=("$@"); break ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -f "${CONFIG}" ]] || { printf 'ERROR: config not found: %s\n' "${CONFIG}" >&2; exit 2; }
[[ "${CORES}" =~ ^[1-9][0-9]*$ ]] || { printf 'ERROR: --cores must be positive.\n' >&2; exit 2; }
[[ "${JOBS}" =~ ^[1-9][0-9]*$ ]] || { printf 'ERROR: --jobs must be positive.\n' >&2; exit 2; }
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

export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${TMPDIR:-/tmp}/e3_workflow_cache_${UID}}"
mkdir -p -- "${XDG_CACHE_HOME}"
mkdir -p "${SCRIPT_DIR}/logs"
LOG="${SCRIPT_DIR}/logs/master_$(date -u '+%Y%m%dT%H%M%SZ').log"
exec > >(tee -a "${LOG}") 2>&1
printf '%s INFO Configuration: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${CONFIG}"
printf '%s INFO Profile: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${PROFILE}"
e3-workflow validate --config "${CONFIG}"

COMMAND=(snakemake --snakefile "${SCRIPT_DIR}/workflow/Snakefile" --configfile "${CONFIG}"
    --profile "${PROFILE}" --rerun-incomplete --printshellcmds --show-failed-logs)
[[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/local" ]] && COMMAND+=(--cores "${CORES}")
[[ "${PROFILE}" == "${SCRIPT_DIR}/profiles/slurm" ]] && COMMAND+=(--jobs "${JOBS}")
[[ "${DRY_RUN}" == "true" ]] && COMMAND+=(--dry-run)
[[ "${UNLOCK}" == "true" ]] && COMMAND+=(--unlock)
[[ -n "${TARGET}" ]] && COMMAND+=("${TARGET}")
COMMAND+=("${EXTRA_ARGS[@]}")
printf 'Command:'; printf ' %q' "${COMMAND[@]}"; printf '\n'
"${COMMAND[@]}"
