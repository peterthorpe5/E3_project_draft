#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/submit_e3_ligandability_slurm.sh \
      ACCESSIONS OUTPUT_DIR [CONFIG_YAML] [CONDA_ENV]

Optional environment overrides:
  E3_SLURM_ACCOUNT    Default: barton
  E3_SLURM_PARTITION  Default: general
  E3_SLURM_CPUS       Default: 8
  E3_SLURM_MEMORY     Default: 32G
  E3_SLURM_TIME       Default: 12:00:00
USAGE
}

if [[ $# -lt 2 || $# -gt 4 ]]; then
    usage >&2
    exit 64
fi

PACKAGE_ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1
    pwd -P
)"
ACCESSIONS="$1"
OUTPUT_DIR="$2"
CONFIG_YAML="${3:-${PACKAGE_ROOT}/config/config.cluster.example.yaml}"
CONDA_ENV="${4:-e3_ligandability}"

ACCOUNT="${E3_SLURM_ACCOUNT:-barton}"
PARTITION="${E3_SLURM_PARTITION:-general}"
CPUS="${E3_SLURM_CPUS:-8}"
MEMORY="${E3_SLURM_MEMORY:-32G}"
WALLTIME="${E3_SLURM_TIME:-12:00:00}"

for command_name in sbatch conda; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "ERROR: Required command not found: ${command_name}" >&2
        exit 69
    fi
done

if [[ ! -f "${ACCESSIONS}" ]]; then
    echo "ERROR: Accession input not found: ${ACCESSIONS}" >&2
    exit 66
fi
ACCESSIONS="$(
    cd -- "$(dirname -- "${ACCESSIONS}")" >/dev/null 2>&1
    printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${ACCESSIONS}")"
)"

if [[ ! -f "${CONFIG_YAML}" ]]; then
    echo "ERROR: Configuration not found: ${CONFIG_YAML}" >&2
    exit 66
fi
CONFIG_YAML="$(
    cd -- "$(dirname -- "${CONFIG_YAML}")" >/dev/null 2>&1
    printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${CONFIG_YAML}")"
)"

mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR="$(cd -- "${OUTPUT_DIR}" >/dev/null 2>&1 && pwd -P)"
mkdir -p "${OUTPUT_DIR}/logs"

CONDA_EXE="$(command -v conda)"
if ! "${CONDA_EXE}" env list | awk '{print $1}' | grep -Fxq "${CONDA_ENV}"; then
    echo "ERROR: Conda environment not found: ${CONDA_ENV}" >&2
    exit 69
fi

JOB_ID="$(
    sbatch \
        --parsable \
        --account="${ACCOUNT}" \
        --partition="${PARTITION}" \
        --nodes=1 \
        --ntasks=1 \
        --cpus-per-task="${CPUS}" \
        --mem="${MEMORY}" \
        --time="${WALLTIME}" \
        --job-name=e3_ligandability \
        --output="${OUTPUT_DIR}/logs/slurm-%j.out" \
        --error="${OUTPUT_DIR}/logs/slurm-%j.err" \
        --export="ALL,CONDA_EXE=${CONDA_EXE}" \
        "${PACKAGE_ROOT}/scripts/slurm_e3_ligandability_job.sh" \
        "${PACKAGE_ROOT}" \
        "${ACCESSIONS}" \
        "${OUTPUT_DIR}" \
        "${CONFIG_YAML}" \
        "${CONDA_ENV}"
)"

printf 'Submitted job: %s\n' "${JOB_ID}"
printf 'Output directory: %s\n' "${OUTPUT_DIR}"
printf 'Check: squeue -j %s\n' "${JOB_ID}"
printf 'Accounting: sacct -j %s --format=JobID,State,Elapsed,TotalCPU,MaxRSS,ExitCode\n' \
    "${JOB_ID}"
