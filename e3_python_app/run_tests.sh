#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "${SCRIPT_DIR}"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
unset PYTEST_ADDOPTS
python -m compileall -q src tests
python -m pycodestyle src tests --max-line-length=100
python -m pydocstyle src/e3app
python -m coverage erase
python -m coverage run --branch -m pytest -q "${SCRIPT_DIR}/tests"
python -m coverage report --fail-under=95
if command -v node >/dev/null 2>&1; then
    node "${SCRIPT_DIR}/tests/js/test_terminal_trim_core.js"
else
    printf '%s\n' "WARNING: node was not found; JavaScript unit tests were not run." >&2
fi
bash -n run_e3_python_app.sh run_tests.sh
