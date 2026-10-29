#!/usr/bin/env bash
# Start a browsing-only viewer locally or on de.NBI.
set -Eeuo pipefail
workbench_conda_exe="${CONDA_EXE:-conda}"
if ! command -v "$workbench_conda_exe" >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: activate the workbench environment or set CONDA_EXE.' >&2
    exit 1
fi
exec "$workbench_conda_exe" run --no-capture-output \
    --name "${POCKET_WORKBENCH_CONDA_ENV:-pocket_workbench}" \
    pocket-workbench app "$@"
