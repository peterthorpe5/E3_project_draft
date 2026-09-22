#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

: "${DIAMOND_BENCHMARK_ROOT:?DIAMOND_BENCHMARK_ROOT is required}"
: "${DIAMOND_BENCHMARK_CONFIG:?DIAMOND_BENCHMARK_CONFIG is required}"
: "${DIAMOND_BENCHMARK_RUN_ROOT:?DIAMOND_BENCHMARK_RUN_ROOT is required}"
: "${DIAMOND_BENCHMARK_ENV:?DIAMOND_BENCHMARK_ENV is required}"

command -v conda >/dev/null 2>&1 || {
    printf 'ERROR: conda is not available\n' >&2
    exit 2
}

printf 'Host: %s\n' "$(hostname)"
printf 'Slurm job: %s\n' "${SLURM_JOB_ID:-not_available}"
printf 'CPUs: %s\n' "${SLURM_CPUS_PER_TASK:-not_available}"
printf 'Benchmark package: %s\n' "${DIAMOND_BENCHMARK_ROOT}"
printf 'Configuration: %s\n' "${DIAMOND_BENCHMARK_CONFIG}"
printf 'Existing run root: %s\n' "${DIAMOND_BENCHMARK_RUN_ROOT}"

cd "${DIAMOND_BENCHMARK_ROOT}"
export PYTHONPATH="${DIAMOND_BENCHMARK_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec conda run --no-capture-output --name "${DIAMOND_BENCHMARK_ENV}" \
    python -m diamond_clust_benchmark.cli report \
    --config "${DIAMOND_BENCHMARK_CONFIG}" \
    --run-root "${DIAMOND_BENCHMARK_RUN_ROOT}"
