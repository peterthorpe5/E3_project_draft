#!/usr/bin/env bash
#SBATCH --job-name=pocket_quality
#SBATCH --account=barton
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=2-00:00:00
#SBATCH --output=pocket_quality-%j.out
#SBATCH --error=pocket_quality-%j.err

# Generic equivalent: supply --models, --output, --fasta and tool paths.
set -Eeuo pipefail
quality_conda_exe="${CONDA_EXE:-conda}"
quality_environment="${POCKET_WORKBENCH_CONDA_ENV:-pocket_workbench}"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
exec "$quality_conda_exe" run --no-capture-output \
    --name "$quality_environment" pocket-workbench-rerun \
    --threads "${SLURM_CPUS_PER_TASK:-8}" \
    --workers "${QUALITY_WORKERS:-4}" "$@"
