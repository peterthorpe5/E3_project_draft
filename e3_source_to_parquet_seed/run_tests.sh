#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$({
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
})"

cd "${SCRIPT_DIR}"

PYTHON_EXE="${PYTHON_EXE:-$(command -v python)}"

[[ -n "${PYTHON_EXE}" ]] || {
    echo "ERROR: Python was not found." >&2
    exit 1
}

for command_name in coverage pycodestyle; do
    command -v "${command_name}" >/dev/null 2>&1 || {
        echo "ERROR: Required test command was not found: ${command_name}" >&2
        exit 1
    }
done

echo "Python: ${PYTHON_EXE}"
"${PYTHON_EXE}" --version

echo "Compiling Python modules"
"${PYTHON_EXE}" -m compileall -q e3parquet scripts tests

echo "Running the complete unittest regression suite"
"${PYTHON_EXE}" \
    -W error::ResourceWarning \
    -m unittest discover -s tests -v

echo "Checking PEP 8 for the new integration layer"
pycodestyle \
    --max-line-length=88 \
    e3parquet/candidate_evidence.py \
    scripts/e3_build_candidate_evidence.py \
    tests/test_candidate_evidence.py \
    tests/test_candidate_evidence_cli.py \
    tests/test_release_contract.py

echo "Checking shell syntax"
bash -n run_e3_candidate_evidence.sh run_e3_seed_pipeline.sh run_tests.sh run_coverage.sh

echo "All release checks passed"
