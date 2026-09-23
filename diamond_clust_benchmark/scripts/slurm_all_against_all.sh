#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

: "${DIAMOND_ALL_PAIRS_ROOT:?DIAMOND_ALL_PAIRS_ROOT is required}"
: "${DIAMOND_ALL_PAIRS_CONFIG:?DIAMOND_ALL_PAIRS_CONFIG is required}"
: "${DIAMOND_ALL_PAIRS_RUN_ROOT:?DIAMOND_ALL_PAIRS_RUN_ROOT is required}"
: "${DIAMOND_ALL_PAIRS_OUTPUT:?DIAMOND_ALL_PAIRS_OUTPUT is required}"
: "${DIAMOND_ALL_PAIRS_ENV:?DIAMOND_ALL_PAIRS_ENV is required}"
: "${DIAMOND_ALL_PAIRS_MEMORY_LIMIT:?DIAMOND_ALL_PAIRS_MEMORY_LIMIT is required}"
: "${DIAMOND_ALL_PAIRS_TEMPORARY:?DIAMOND_ALL_PAIRS_TEMPORARY is required}"

command -v conda >/dev/null 2>&1 || {
    printf 'ERROR: conda is not available\n' >&2
    exit 2
}

printf 'Host: %s\n' "$(hostname)"
printf 'Slurm job: %s\n' "${SLURM_JOB_ID:-not_available}"
printf 'CPUs: %s\n' "${SLURM_CPUS_PER_TASK:-not_available}"
printf 'Benchmark package: %s\n' "${DIAMOND_ALL_PAIRS_ROOT}"
printf 'Configuration: %s\n' "${DIAMOND_ALL_PAIRS_CONFIG}"
printf 'Existing run root: %s\n' "${DIAMOND_ALL_PAIRS_RUN_ROOT}"
printf 'Analysis output: %s\n' "${DIAMOND_ALL_PAIRS_OUTPUT}"
printf 'DuckDB memory limit: %s\n' "${DIAMOND_ALL_PAIRS_MEMORY_LIMIT}"

THREADS="${SLURM_CPUS_PER_TASK:-2}"
ARGUMENTS=(
    --config "${DIAMOND_ALL_PAIRS_CONFIG}"
    --run-root "${DIAMOND_ALL_PAIRS_RUN_ROOT}"
    --output-directory "${DIAMOND_ALL_PAIRS_OUTPUT}"
    --threads "${THREADS}"
    --memory-limit "${DIAMOND_ALL_PAIRS_MEMORY_LIMIT}"
    --temporary-directory "${DIAMOND_ALL_PAIRS_TEMPORARY}"
    --formats png pdf
)

if [[ -n "${DIAMOND_ALL_PAIRS_SENTINELS:-}" ]]; then
    ARGUMENTS+=(--sentinel-ids-tsv "${DIAMOND_ALL_PAIRS_SENTINELS}")
fi
if [[ "${DIAMOND_ALL_PAIRS_RESUME:-false}" == "true" ]]; then
    ARGUMENTS+=(--resume)
fi

cd "${DIAMOND_ALL_PAIRS_ROOT}"
exec conda run --no-capture-output --name "${DIAMOND_ALL_PAIRS_ENV}" \
    python scripts/compare_all_memberships.py "${ARGUMENTS[@]}"
