#!/usr/bin/env bash
#SBATCH --job-name=pocket_build
#SBATCH --account=barton
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=2-00:00:00
#SBATCH --output=pocket_build-%j.out
#SBATCH --error=pocket_build-%j.err

# Generic Dundee worker. Arguments after the script are named build CLI options.
set -Eeuo pipefail
workbench_conda_exe="${CONDA_EXE:-conda}"
workbench_environment="${POCKET_WORKBENCH_CONDA_ENV:-pocket_workbench}"
if ! command -v "$workbench_conda_exe" >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: Conda unavailable. Export CONDA_EXE before sbatch.' >&2
    exit 1
fi
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
printf 'Host: %s\nSlurm job: %s\n' "$(hostname)" "${SLURM_JOB_ID:-local}"
exec "$workbench_conda_exe" run --no-capture-output \
    --name "$workbench_environment" pocket-workbench build "$@"
