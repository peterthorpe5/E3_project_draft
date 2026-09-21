#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

python -m compileall -q src tests
pycodestyle src tests --max-line-length=88
coverage erase
coverage run --source=src/diamond_clust_benchmark -m unittest discover -s tests -v
coverage report --fail-under=95 -m
