#!/usr/bin/env bash
# Slurm execution target. Scheduler resources are supplied by the submit wrapper.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PACKAGE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

printf '%s\tINFO\tSlurm job %s started on %s.\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_JOB_ID:-unknown}" "$(hostname)"
printf '%s\tINFO\tAllocated CPUs: %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${SLURM_CPUS_PER_TASK:-unknown}"

"${PACKAGE_DIR}/run_e3_orthology_integration.sh" "$@"

printf '%s\tINFO\tSlurm job completed.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
