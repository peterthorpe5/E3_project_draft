#!/usr/bin/env bash
#SBATCH --job-name=protein_pockets
#SBATCH --account=barton
#SBATCH --partition=general
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=protein_pockets-%j.log

set -euo pipefail

if ! command -v protein-pockets >/dev/null 2>&1; then
    printf '%s\n' 'Activate the protein_pockets environment before submitting.' >&2
    exit 1
fi

exec protein-pockets run --threads "${SLURM_CPUS_PER_TASK:-4}" "$@"
