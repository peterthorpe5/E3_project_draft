#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PACKAGE_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"

python "${PACKAGE_DIR}/inst/python/prepare_existing_atlas_downloads.py" "$@"
