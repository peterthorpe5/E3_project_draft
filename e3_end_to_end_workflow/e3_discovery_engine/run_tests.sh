#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

python -m compileall -q src tests
pycodestyle src tests scripts --max-line-length=88
coverage erase
coverage run --source=src/e3_discovery -m unittest discover -s tests -v
coverage report --fail-under=98 -m
