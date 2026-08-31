#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
cd "$PACKAGE_ROOT"

python -m coverage erase
python -m coverage run --branch -m pytest -q
python -m coverage report --show-missing --fail-under=95
python -m pycodestyle --ignore=E203,E501,W503 src tests
python -m pydocstyle src
python -m ruff check src tests
python -m compileall -q src tests
bash -n run_orthofinder_results.sh
bash -n submit_orthofinder_results_slurm.sh
bash -n slurm/orthofinder_results.sbatch
