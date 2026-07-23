#!/usr/bin/env bash
# Run all structural-alignment tests and quality gates.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "${SCRIPT_DIR}"

python -m coverage erase
python -m coverage run --branch -m pytest
python -m coverage report
python -m pycodestyle src tests --max-line-length=100
python -m pydocstyle src tests
bash -n run_e3_structural_alignment.sh run_tests.sh
