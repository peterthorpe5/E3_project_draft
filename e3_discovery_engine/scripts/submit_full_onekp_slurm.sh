#!/usr/bin/env bash
# Submit the full inherited 1KP+ E3 Discovery Engine analysis to Slurm.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SOURCE_ROOT="/home/pthorpe001/data/2026_E3_protac/SSD_back_up_July_2026/Erin_Butterfield_data"
RESULTS_BASE="/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results"
ACCOUNT="barton"
PARTITION="general"
CPUS=32
SLURM_MEMORY="256G"
DIAMOND_MEMORY="220G"
WALLTIME="7-00:00:00"
CONDA_ENV="e3_discovery"
MIN_RESULTS_FREE_GIB=150
MIN_SCRATCH_FREE_GIB=100
SCRATCH_BASE=""
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
JOB_NAME="e3_onekp_full"

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/submit_full_onekp_slurm.sh [options]

Options:
  --source-root PATH       Cluster path to Erin_Butterfield_data.
  --results-base PATH      Persistent cluster results directory.
  --account NAME           Slurm account. Default: barton.
  --partition NAME         Slurm partition. Default: general.
  --cpus INTEGER           CPUs per task. Default: 32.
  --memory VALUE           Slurm memory request. Default: 256G.
  --diamond-memory VALUE   DIAMOND memory limit. Default: 220G.
  --time VALUE             Slurm wall-time limit. Default: 7-00:00:00.
  --conda-env NAME         Existing bootstrap Conda environment.
  --min-results-free-gib N Minimum free persistent space. Default: 150.
  --min-scratch-free-gib N Minimum free scratch space. Default: 100.
  --scratch-base PATH      Optional fast node-local scratch base.
  --run-tag TEXT           Stable run tag for output naming/resumption.
  --job-name TEXT          Slurm job name.
  -h, --help               Show this help.

The script submits one Slurm job. The job creates the full 1KP+ manifest and
configuration, runs Snakemake, validates the result, and writes a compact
review bundle alongside the full persistent output.
USAGE
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 2
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --source-root) SOURCE_ROOT="${2:?}"; shift 2 ;;
        --results-base) RESULTS_BASE="${2:?}"; shift 2 ;;
        --account) ACCOUNT="${2:?}"; shift 2 ;;
        --partition) PARTITION="${2:?}"; shift 2 ;;
        --cpus) CPUS="${2:?}"; shift 2 ;;
        --memory) SLURM_MEMORY="${2:?}"; shift 2 ;;
        --diamond-memory) DIAMOND_MEMORY="${2:?}"; shift 2 ;;
        --time) WALLTIME="${2:?}"; shift 2 ;;
        --conda-env) CONDA_ENV="${2:?}"; shift 2 ;;
        --min-results-free-gib) MIN_RESULTS_FREE_GIB="${2:?}"; shift 2 ;;
        --min-scratch-free-gib) MIN_SCRATCH_FREE_GIB="${2:?}"; shift 2 ;;
        --scratch-base) SCRATCH_BASE="${2:?}"; shift 2 ;;
        --run-tag) RUN_TAG="${2:?}"; shift 2 ;;
        --job-name) JOB_NAME="${2:?}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ "${CPUS}" =~ ^[1-9][0-9]*$ ]] || die "--cpus must be a positive integer"
[[ "${MIN_RESULTS_FREE_GIB}" =~ ^[1-9][0-9]*$ ]] || die "--min-results-free-gib must be a positive integer"
[[ "${MIN_SCRATCH_FREE_GIB}" =~ ^[1-9][0-9]*$ ]] || die "--min-scratch-free-gib must be a positive integer"
[[ -d "${REPO_ROOT}" ]] || die "Repository root not found: ${REPO_ROOT}"
[[ -f "${REPO_ROOT}/Snakefile" ]] || die "Snakefile not found in ${REPO_ROOT}"
[[ -d "${SOURCE_ROOT}" ]] || die "Source root not found: ${SOURCE_ROOT}"
command -v sbatch >/dev/null 2>&1 || die "sbatch is not available"

RESULTS_BASE="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${RESULTS_BASE}")"
SOURCE_ROOT="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${SOURCE_ROOT}")"
REPO_ROOT="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${REPO_ROOT}")"

RUN_ROOT="${RESULTS_BASE}/full_onekp_plus_v0_1_13_${RUN_TAG}"
SETUP_DIR="${RUN_ROOT}/run_setup"
SLURM_LOG_DIR="${RESULTS_BASE}/slurm_logs/full_onekp_plus_v0_1_13_${RUN_TAG}"
REVIEW_DIR="${RESULTS_BASE}/review_bundles"

if [[ -e "${RUN_ROOT}/workflow_complete.ok" ]]; then
    die "Run is already marked complete: ${RUN_ROOT}"
fi

mkdir -p "${SETUP_DIR}" "${SLURM_LOG_DIR}" "${REVIEW_DIR}"

EXPORTS="ALL"
EXPORTS+=",E3_REPO_ROOT=${REPO_ROOT}"
EXPORTS+=",E3_SOURCE_ROOT=${SOURCE_ROOT}"
EXPORTS+=",E3_RESULTS_BASE=${RESULTS_BASE}"
EXPORTS+=",E3_RUN_ROOT=${RUN_ROOT}"
EXPORTS+=",E3_SETUP_DIR=${SETUP_DIR}"
EXPORTS+=",E3_REVIEW_DIR=${REVIEW_DIR}"
EXPORTS+=",E3_THREADS=${CPUS}"
EXPORTS+=",E3_DIAMOND_MEMORY=${DIAMOND_MEMORY}"
EXPORTS+=",E3_CONDA_ENV=${CONDA_ENV}"
EXPORTS+=",E3_MIN_RESULTS_FREE_GIB=${MIN_RESULTS_FREE_GIB}"
EXPORTS+=",E3_MIN_SCRATCH_FREE_GIB=${MIN_SCRATCH_FREE_GIB}"
if [[ -n "${SCRATCH_BASE}" ]]; then
    EXPORTS+=",E3_SCRATCH_BASE=${SCRATCH_BASE}"
fi
EXPORTS+=",E3_RUN_TAG=${RUN_TAG}"

JOB_ID="$(
    sbatch \
        --parsable \
        --job-name="${JOB_NAME}" \
        --account="${ACCOUNT}" \
        --partition="${PARTITION}" \
        --nodes=1 \
        --ntasks=1 \
        --cpus-per-task="${CPUS}" \
        --mem="${SLURM_MEMORY}" \
        --time="${WALLTIME}" \
        --output="${SLURM_LOG_DIR}/slurm-%j.out" \
        --error="${SLURM_LOG_DIR}/slurm-%j.err" \
        --export="${EXPORTS}" \
        "${REPO_ROOT}/scripts/slurm_full_onekp_job.sh"
)"
JOB_ID="${JOB_ID%%;*}"

cat > "${SLURM_LOG_DIR}/job_info.tsv" <<INFO
field	value
job_id	${JOB_ID}
run_tag	${RUN_TAG}
repository	${REPO_ROOT}
source_root	${SOURCE_ROOT}
results_root	${RUN_ROOT}
setup_dir	${SETUP_DIR}
review_dir	${REVIEW_DIR}
account	${ACCOUNT}
partition	${PARTITION}
cpus	${CPUS}
slurm_memory	${SLURM_MEMORY}
diamond_memory	${DIAMOND_MEMORY}
walltime	${WALLTIME}
conda_environment	${CONDA_ENV}
minimum_results_free_gib	${MIN_RESULTS_FREE_GIB}
minimum_scratch_free_gib	${MIN_SCRATCH_FREE_GIB}
scratch_base	${SCRATCH_BASE:-Slurm_or_system_default}
stdout	${SLURM_LOG_DIR}/slurm-${JOB_ID}.out
stderr	${SLURM_LOG_DIR}/slurm-${JOB_ID}.err
INFO

printf 'Submitted Slurm job: %s\n' "${JOB_ID}"
printf 'Full result root:    %s\n' "${RUN_ROOT}"
printf 'Standard output:     %s\n' "${SLURM_LOG_DIR}/slurm-${JOB_ID}.out"
printf 'Standard error:      %s\n' "${SLURM_LOG_DIR}/slurm-${JOB_ID}.err"
printf '\nCheck the job with:\n'
printf '  squeue -j %s\n' "${JOB_ID}"
printf '  ./scripts/check_full_onekp_slurm.sh --job-id %s\n' "${JOB_ID}"
printf '  tail -f %q\n' "${SLURM_LOG_DIR}/slurm-${JOB_ID}.out"
