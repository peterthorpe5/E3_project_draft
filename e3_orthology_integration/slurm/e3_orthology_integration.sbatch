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

REQUESTED_CPUS="${E3_REQUESTED_CPUS:-}"
ALLOCATED_CPUS="${SLURM_CPUS_PER_TASK:-}"
if [[ ! "${REQUESTED_CPUS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: E3_REQUESTED_CPUS is missing or invalid: %s\n' \
        "${REQUESTED_CPUS:-unset}" >&2
    exit 2
fi
if [[ ! "${ALLOCATED_CPUS}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'ERROR: SLURM_CPUS_PER_TASK is missing or invalid: %s\n' \
        "${ALLOCATED_CPUS:-unset}" >&2
    exit 2
fi
if [[ "${ALLOCATED_CPUS}" != "${REQUESTED_CPUS}" ]]; then
    printf 'ERROR: Slurm CPU mismatch: requested %s but allocated %s per task.\n' \
        "${REQUESTED_CPUS}" "${ALLOCATED_CPUS}" >&2
    exit 2
fi

printf '%s\tINFO\tSlurm job %s started on %s.\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_JOB_ID:-unknown}" "$(hostname)"
printf '%s\tINFO\tRequested and allocated CPUs per task: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${ALLOCATED_CPUS}"
printf '%s\tINFO\tPipeline runner: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${RUNNER}"

"${RUNNER}" "$@"

printf '%s\tINFO\tSlurm job completed.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
