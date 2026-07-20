#!/usr/bin/env bash
# Execute the production quality gates in a configured Python environment.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "${SCRIPT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python}"

"${PYTHON_BIN}" -m compileall -q e3orthology tests
"${PYTHON_BIN}" -m coverage erase
"${PYTHON_BIN}" -m coverage run --branch -m unittest discover -s tests -t . -v
"${PYTHON_BIN}" -m coverage report --show-missing --fail-under=95
"${PYTHON_BIN}" -m pycodestyle --max-line-length=100 e3orthology tests
"${PYTHON_BIN}" -m ruff check e3orthology tests
"${PYTHON_BIN}" -m pydocstyle --convention=google \
    --add-ignore=D104,D105,D107,D202 e3orthology
bash -n run_e3_orthology_integration.sh
bash -n submit_e3_orthology_integration.sh
bash -n slurm/e3_orthology_integration.sbatch

printf 'All e3_orthology_integration quality gates passed.\n'
