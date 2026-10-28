#!/usr/bin/env bash
#SBATCH --job-name=pocket_compare
#SBATCH --account=barton
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=1-00:00:00
#SBATCH --output=pocket_compare-%j.out
#SBATCH --error=pocket_compare-%j.err

set -euo pipefail
workbench_conda_exe="${CONDA_EXE:-conda}"
if ! command -v "$workbench_conda_exe" >/dev/null 2>&1; then
    printf '%s\n' 'Conda unavailable: activate pocket_workbench or export CONDA_EXE before sbatch.' >&2
    exit 1
fi
exec "$workbench_conda_exe" run --no-capture-output --name pocket_workbench \
    pocket-workbench compare "$@"
