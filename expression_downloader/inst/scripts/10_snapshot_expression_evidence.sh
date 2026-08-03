#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec python \
    "${PACKAGE_ROOT}/inst/python/snapshot_expression_evidence.py" \
    "$@"
