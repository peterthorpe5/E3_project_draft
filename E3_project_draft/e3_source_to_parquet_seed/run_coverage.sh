#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$({
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
})"

cd "${SCRIPT_DIR}"

command -v coverage >/dev/null 2>&1 || {
    echo "ERROR: coverage was not found." >&2
    exit 1
}

coverage erase
coverage run \
    --branch \
    --source=e3parquet.candidate_evidence \
    -m unittest \
    tests.test_candidate_evidence \
    tests.test_candidate_evidence_cli \
    tests.test_release_contract
coverage report --fail-under=99
