#!/usr/bin/env bash
# Execute the human-and-plant Snakemake controller inside a Slurm allocation.

set -Eeuo pipefail

if (($# < 4)); then
    printf 'ERROR: controller requires CONDA, ENVIRONMENT, RUNNER and runner arguments.\n' >&2
    exit 2
fi

readonly CONDA_EXECUTABLE="$1"
readonly CONDA_ENVIRONMENT="$2"
readonly RUNNER="$3"
shift 3

[[ -x "${CONDA_EXECUTABLE}" ]] || {
    printf 'ERROR: Conda executable is not executable: %s\n' "${CONDA_EXECUTABLE}" >&2
    exit 2
}
[[ -x "${RUNNER}" ]] || {
    printf 'ERROR: extension runner is not executable: %s\n' "${RUNNER}" >&2
    exit 2
}

exec "${CONDA_EXECUTABLE}" run --no-capture-output --name "${CONDA_ENVIRONMENT}" \
    "${RUNNER}" "$@"
