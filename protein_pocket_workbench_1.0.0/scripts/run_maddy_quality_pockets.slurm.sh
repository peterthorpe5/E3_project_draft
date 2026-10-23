#!/usr/bin/env bash
#SBATCH --job-name=maddy_quality
#SBATCH --account=barton
#SBATCH --partition=barton
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=2-00:00:00
#SBATCH --output=maddy_quality-%j.out
#SBATCH --error=maddy_quality-%j.err

# Complete batch workflow; no inline Python and no work is launched by the app.
# Extra arguments are named pocket-workbench-rerun options (e.g. --resume).
set -Eeuo pipefail

quality_project="${MADDY_PROJECT:-$HOME/data/2026_E3_protac/2026_oct_Maddy_BRCA1_pockets}"
quality_output="${QUALITY_RESULT_ROOT:-$quality_project/results/pockets_quality_regions_v1}"
quality_conda_exe="${CONDA_EXE:-conda}"
quality_environment="${POCKET_WORKBENCH_CONDA_ENV:-pocket_workbench}"
quality_p2rank="${POCKET_WORKBENCH_P2RANK:-$quality_project/software/p2rank_2.5.1/prank}"
quality_threads="${SLURM_CPUS_PER_TASK:-8}"
quality_workers="${QUALITY_WORKERS:-4}"

if ! command -v "$quality_conda_exe" >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: Conda unavailable. Activate the environment or export CONDA_EXE.' >&2
    exit 1
fi
if [[ ! -d "$quality_project/alpha_fold_models" || ! -s "$quality_project/BRCA1_all_reps.fasta" ]]; then
    printf '%s\n' 'ERROR: Expected alpha_fold_models/ and BRCA1_all_reps.fasta under MADDY_PROJECT.' >&2
    exit 1
fi
# Tool checks belong to the Python CLI so --prepare-only needs no predictors.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

printf 'Host: %s\nSlurm job: %s\nNew results: %s\n' \
    "$(hostname)" "${SLURM_JOB_ID:-local}" "$quality_output"

exec "$quality_conda_exe" run --no-capture-output \
    --name "$quality_environment" pocket-workbench-rerun \
    --models "$quality_project/alpha_fold_models" \
    --fasta "$quality_project/BRCA1_all_reps.fasta" \
    --output "$quality_output" \
    --title 'Maddy BRCA1: quality-prepared pocket review' \
    --p2rank "$quality_p2rank" \
    --fpocket fpocket \
    --threads "$quality_threads" \
    --workers "$quality_workers" \
    --comparison-mode matched_reference \
    --bootstrap 100 \
    "$@"
