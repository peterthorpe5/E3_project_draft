#!/usr/bin/env bash
# Slurm execution target. Scheduler resources are supplied by the submit wrapper.

set -Eeuo pipefail

if (($# < 1)); then
    printf 'ERROR: the absolute pipeline runner path was not supplied.\n' >&2
    exit 2
fi

RUNNER="$1"
shift

if [[ "${RUNNER}" != /* ]]; then
    printf 'ERROR: pipeline runner path is not absolute: %s\n' "${RUNNER}" >&2
    exit 2
fi
if [[ ! -f "${RUNNER}" || ! -x "${RUNNER}" ]]; then
    printf 'ERROR: pipeline runner is missing or not executable: %s\n' "${RUNNER}" >&2
    exit 2
fi

printf '%s\tINFO\tSlurm job %s started on %s.\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_JOB_ID:-unknown}" "$(hostname)"
printf '%s\tINFO\tAllocated CPUs: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_CPUS_PER_TASK:-unknown}"
printf '%s\tINFO\tPipeline runner: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${RUNNER}"

"${RUNNER}" "$@"

printf '%s\tINFO\tSlurm job completed.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
