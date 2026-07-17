#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
)"
cd "${PACKAGE_ROOT}"

coverage erase
coverage run --branch -m unittest discover -s tests
coverage report --show-missing
coverage xml -o coverage.xml
