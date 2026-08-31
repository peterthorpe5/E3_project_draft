#!/usr/bin/env bash
set -euo pipefail

[[ $# -ge 3 ]] || { echo "ERROR: package root, conda environment and package arguments required." >&2; exit 2; }
PACKAGE_ROOT=$1
CONDA_ENV=$2
shift 2

[[ -x "$PACKAGE_ROOT/run_orthofinder_results.sh" ]] || {
    echo "ERROR: package runner is not executable: $PACKAGE_ROOT/run_orthofinder_results.sh" >&2
    exit 2
}

echo "Host: $(hostname)"
echo "Started: $(date --iso-8601=seconds)"
echo "Slurm job: ${SLURM_JOB_ID:-unavailable}"
echo "Allocated CPUs: ${SLURM_CPUS_PER_TASK:-unavailable}"

HAS_WORK_DIR=false
for argument in "$@"; do
    case "$argument" in
        --work-dir|--work-dir=*) HAS_WORK_DIR=true; break ;;
    esac
done

if [[ "$HAS_WORK_DIR" == false ]]; then
    NODE_TEMP_ROOT=${TMPDIR:-/tmp}
    [[ -d "$NODE_TEMP_ROOT" && -w "$NODE_TEMP_ROOT" ]] || {
        echo "ERROR: node-local temporary root is unavailable: $NODE_TEMP_ROOT" >&2
        exit 2
    }
    NODE_WORK_DIR="$NODE_TEMP_ROOT/orthofinder_results_${USER}_${SLURM_JOB_ID}"
    umask 077
    mkdir -p "$NODE_WORK_DIR"
    trap 'rmdir "$NODE_WORK_DIR" 2>/dev/null || true' EXIT
    echo "Node-local work directory: $NODE_WORK_DIR"
    set -- "$@" --work-dir "$NODE_WORK_DIR"
else
    echo "Using explicitly supplied work directory."
fi

"$PACKAGE_ROOT/run_orthofinder_results.sh" --conda-env "$CONDA_ENV" -- "$@"

echo "Finished: $(date --iso-8601=seconds)"
