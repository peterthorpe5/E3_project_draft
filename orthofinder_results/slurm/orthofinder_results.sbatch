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

"$PACKAGE_ROOT/run_orthofinder_results.sh" --conda-env "$CONDA_ENV" -- "$@"

echo "Finished: $(date --iso-8601=seconds)"
