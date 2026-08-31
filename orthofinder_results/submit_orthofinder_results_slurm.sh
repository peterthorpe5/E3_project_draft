#!/usr/bin/env bash
set -euo pipefail

ACCOUNT="barton"
PARTITION="general"
QOS=""
CPUS="8"
MEMORY="64G"
WALLTIME="24:00:00"
CONDA_ENV="orthofinder_results"
SLURM_LOG_DIR=""
PACKAGE_ARGS=()

usage() {
    echo "Usage: $0 --slurm-log-dir DIR [scheduler options] -- [orthofinder-results options]" >&2
}

while (($#)); do
    case "$1" in
        --account) ACCOUNT=$2; shift 2 ;;
        --partition) PARTITION=$2; shift 2 ;;
        --qos) QOS=$2; shift 2 ;;
        --cpus-per-task) CPUS=$2; shift 2 ;;
        --memory) MEMORY=$2; shift 2 ;;
        --time) WALLTIME=$2; shift 2 ;;
        --conda-env) CONDA_ENV=$2; shift 2 ;;
        --slurm-log-dir) SLURM_LOG_DIR=$2; shift 2 ;;
        --) shift; PACKAGE_ARGS=("$@"); break ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown scheduler option: $1" >&2; usage; exit 2 ;;
    esac
done

[[ -n "$SLURM_LOG_DIR" ]] || { echo "ERROR: --slurm-log-dir is required." >&2; exit 2; }
((${#PACKAGE_ARGS[@]})) || { echo "ERROR: Package options are required after --." >&2; exit 2; }
[[ "$CPUS" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --cpus-per-task must be positive." >&2; exit 2; }

PACKAGE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SLURM_LOG_DIR=$(mkdir -p "$SLURM_LOG_DIR" && cd "$SLURM_LOG_DIR" && pwd -P)
SBATCH_ARGS=(
    --parsable
    --account "$ACCOUNT"
    --partition "$PARTITION"
    --nodes 1
    --ntasks 1
    --cpus-per-task "$CPUS"
    --mem "$MEMORY"
    --time "$WALLTIME"
    --job-name orthofinder_results
    --output "$SLURM_LOG_DIR/orthofinder_results_%j.out"
    --error "$SLURM_LOG_DIR/orthofinder_results_%j.err"
)
if [[ -n "$QOS" ]]; then
    SBATCH_ARGS+=(--qos "$QOS")
fi

JOB_ID=$(sbatch "${SBATCH_ARGS[@]}" \
    "$PACKAGE_ROOT/slurm/orthofinder_results.sbatch" \
    "$PACKAGE_ROOT" "$CONDA_ENV" "${PACKAGE_ARGS[@]}")

echo "Submitted job: $JOB_ID"
echo "Slurm stdout: $SLURM_LOG_DIR/orthofinder_results_${JOB_ID}.out"
echo "Slurm stderr: $SLURM_LOG_DIR/orthofinder_results_${JOB_ID}.err"
echo "Monitor: squeue -j $JOB_ID"
