#!/usr/bin/env bash
# Run the open-source E3 structure-guided chemistry package.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ "${1-}" == "--help" || "${1-}" == "-h" ]]; then
    exec e3-chemistry run --help
fi

command -v e3-chemistry >/dev/null || {
    printf 'ERROR: e3-chemistry is not installed in the active environment.\n' >&2
    printf 'Install the package from: %s\n' "${SCRIPT_DIR}" >&2
    exit 2
}

exec e3-chemistry run "$@"
