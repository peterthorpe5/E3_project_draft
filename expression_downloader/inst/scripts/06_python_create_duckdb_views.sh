#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec python \
  "${PACKAGE_DIR}/inst/python/build_expression_duckdb.py" \
  "$@"
