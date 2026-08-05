#!/usr/bin/env bash
# Repository-level launcher for the tested captured-source rebuild workflow.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly IMPLEMENTATION="${SCRIPT_DIR}/inst/scripts/run_clean_rebuild_from_existing.sh"

if [[ ! -x "${IMPLEMENTATION}" ]]; then
    printf 'ERROR: rebuild implementation is missing or not executable: %s\n' \
        "${IMPLEMENTATION}" >&2
    exit 2
fi

exec "${IMPLEMENTATION}" "$@"
