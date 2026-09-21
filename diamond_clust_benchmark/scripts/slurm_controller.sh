#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

: "${DIAMOND_BENCHMARK_ROOT:?DIAMOND_BENCHMARK_ROOT is required}"
: "${DIAMOND_BENCHMARK_CONFIG:?DIAMOND_BENCHMARK_CONFIG is required}"
: "${DIAMOND_BENCHMARK_ENV:?DIAMOND_BENCHMARK_ENV is required}"

command -v conda >/dev/null 2>&1 || {
    printf 'ERROR: conda is not available\n' >&2
    exit 2
}

printf 'Host: %s\n' "$(hostname)"
printf 'Slurm job: %s\n' "${SLURM_JOB_ID:-not_available}"
printf 'CPUs: %s\n' "${SLURM_CPUS_PER_TASK:-not_available}"
printf 'Benchmark root: %s\n' "${DIAMOND_BENCHMARK_ROOT}"
printf 'Configuration: %s\n' "${DIAMOND_BENCHMARK_CONFIG}"

cd "${DIAMOND_BENCHMARK_ROOT}"
exec conda run --no-capture-output --name "${DIAMOND_BENCHMARK_ENV}" \
    bash ./run_workflow.sh \
    --config "${DIAMOND_BENCHMARK_CONFIG}" \
    --cores "${SLURM_CPUS_PER_TASK:-1}"
