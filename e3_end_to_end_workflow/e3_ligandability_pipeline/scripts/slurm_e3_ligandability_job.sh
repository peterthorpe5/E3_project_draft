#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
    echo "Usage: $0 PACKAGE_ROOT ACCESSIONS OUTPUT_DIR CONFIG_YAML CONDA_ENV" >&2
    exit 64
fi

PACKAGE_ROOT="$1"
ACCESSIONS="$2"
OUTPUT_DIR="$3"
CONFIG_YAML="$4"
CONDA_ENV="$5"

if [[ -z "${CONDA_EXE:-}" || ! -x "${CONDA_EXE}" ]]; then
    echo "ERROR: CONDA_EXE was not supplied or is not executable." >&2
    exit 69
fi

for required_path in "${PACKAGE_ROOT}" "${ACCESSIONS}" "${CONFIG_YAML}"; do
    if [[ ! -e "${required_path}" ]]; then
        echo "ERROR: Required path is missing: ${required_path}" >&2
        exit 66
    fi
done

mkdir -p "${OUTPUT_DIR}/provenance"
METADATA_PATH="${OUTPUT_DIR}/provenance/slurm_job_metadata.tsv"
{
    printf 'field\tvalue\n'
    printf 'job_id\t%s\n' "${SLURM_JOB_ID:-NA}"
    printf 'job_name\t%s\n' "${SLURM_JOB_NAME:-NA}"
    printf 'node_list\t%s\n' "${SLURM_JOB_NODELIST:-NA}"
    printf 'allocated_cpus\t%s\n' "${SLURM_CPUS_PER_TASK:-NA}"
    printf 'submit_directory\t%s\n' "${SLURM_SUBMIT_DIR:-NA}"
    printf 'started_at_utc\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${METADATA_PATH}"

export CONDA_EXE
exec "${PACKAGE_ROOT}/run_e3_ligandability.sh" \
    "${ACCESSIONS}" \
    "${OUTPUT_DIR}" \
    "${CONFIG_YAML}" \
    "${CONDA_ENV}"
