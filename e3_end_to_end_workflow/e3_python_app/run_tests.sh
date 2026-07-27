#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "${SCRIPT_DIR}"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
python -m compileall -q src tests
python -m pycodestyle src tests --max-line-length=100
python -m pydocstyle src/e3app
python -m coverage erase
python -m coverage run --branch -m pytest -q
python -m coverage report --fail-under=95
bash -n run_e3_python_app.sh run_tests.sh
