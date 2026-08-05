#!/usr/bin/env bash
# Repository-level launcher for the tested live Expression Atlas workflow.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly IMPLEMENTATION="${SCRIPT_DIR}/inst/scripts/run_python_first_then_r.sh"

if [[ ! -x "${IMPLEMENTATION}" ]]; then
    printf 'ERROR: live workflow implementation is missing or not executable: %s\n' \
        "${IMPLEMENTATION}" >&2
    exit 2
fi

exec "${IMPLEMENTATION}" "$@"
