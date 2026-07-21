#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "${SCRIPT_DIR}"
python -m compileall -q src tests
python -m pycodestyle src tests --max-line-length=100
python -m pydocstyle src/e3workflow
python -m coverage erase
python -m coverage run --branch -m pytest -q
python -m coverage report --fail-under=95
bash -n run_e3_end_to_end.sh run_tests.sh
if command -v snakemake >/dev/null 2>&1; then
    snakemake --snakefile workflow/Snakefile --configfile config/synthetic.yaml --lint
    ./run_e3_end_to_end.sh --dry-run
fi

