#!/usr/bin/env bash
# Slurm worker for the full inherited 1KP+ E3 Discovery Engine analysis.

#SBATCH --account=barton
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=7-00:00:00
#SBATCH --job-name=e3_onekp_full

set -Eeuo pipefail
IFS=$'\n\t'
umask 027

CURRENT_STAGE="initialisation"
JOB_STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
JOB_SCRATCH=""
REMOVE_SCRATCH_ON_EXIT=0

log() {
    printf '%s [INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

error() {
    printf '%s [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >&2
}

write_failure_marker() {
    local exit_code="$1"
    if [[ -n "${E3_RUN_ROOT:-}" ]]; then
        mkdir -p "${E3_RUN_ROOT}"
        cat > "${E3_RUN_ROOT}/workflow_failed.tsv" <<FAIL
field	value
job_id	${SLURM_JOB_ID:-not_available}
stage	${CURRENT_STAGE}
exit_code	${exit_code}
failed_at_utc	$(date -u +%Y-%m-%dT%H:%M:%SZ)
scratch	${JOB_SCRATCH}
FAIL
    fi
}

on_error() {
    local exit_code=$?
    error "Full 1KP+ workflow failed during ${CURRENT_STAGE} (exit ${exit_code})."
    write_failure_marker "${exit_code}"
    if [[ -n "${JOB_SCRATCH}" ]]; then
        error "Scratch has been retained for diagnosis: ${JOB_SCRATCH}"
    fi
    exit "${exit_code}"
}

on_exit() {
    local exit_code=$?
    if [[
        "${exit_code}" -eq 0 &&
        "${REMOVE_SCRATCH_ON_EXIT}" -eq 1 &&
        -n "${JOB_SCRATCH}"
    ]]; then
        rm -rf -- "${JOB_SCRATCH}" || true
    fi
    exit "${exit_code}"
}

trap on_error ERR
trap 'error "Job interrupted during ${CURRENT_STAGE}"; write_failure_marker 130; exit 130' INT TERM
trap on_exit EXIT

require_variable() {
    local name="$1"
    [[ -n "${!name:-}" ]] || {
        error "Required environment variable is unset: ${name}"
        exit 2
    }
}

check_free_space_gib() {
    local path="$1"
    local required_gib="$2"
    local label="$3"
    local available_kib=""
    local available_gib=""
    local required_kib=""

    available_kib="$(df -Pk "${path}" | awk 'NR == 2 {print $4}')"
    [[ "${available_kib}" =~ ^[0-9]+$ ]] || {
        error "Could not determine free space for ${label}: ${path}"
        return 2
    }

    required_kib=$((required_gib * 1024 * 1024))
    available_gib=$((available_kib / 1024 / 1024))
    log "Free space for ${label}: ${available_gib} GiB at ${path}"

    if (( available_kib < required_kib )); then
        error "Insufficient free space for ${label}: ${available_gib} GiB available; ${required_gib} GiB required at ${path}"
        return 2
    fi
}

activate_conda_environment() {
    local environment_name="$1"
    local conda_base=""

    if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
        conda_base="$(cd "$(dirname "${CONDA_EXE}")/.." && pwd)"
    elif [[ -f "${HOME}/miniforge3/etc/profile.d/conda.sh" ]]; then
        conda_base="${HOME}/miniforge3"
    elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
        conda_base="${HOME}/miniconda3"
    else
        error "Could not locate conda.sh under CONDA_EXE, miniforge3 or miniconda3."
        return 2
    fi

    # shellcheck disable=SC1091
    source "${conda_base}/etc/profile.d/conda.sh"
    conda activate "${environment_name}"
}

validate_completed_result() {
    local run_root="$1"
    python - "${run_root}" <<'PY'
"""Validate the completed full-run QC and resource-monitor tables."""

import csv
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
validation_path = root / "qc" / "resource_validation.tsv"
resource_path = root / "benchmark_summary" / "resource_usage_summary.tsv"

for path in (validation_path, resource_path):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Required completed-run file is missing: {path}")

with validation_path.open("r", encoding="utf-8-sig", newline="") as handle:
    findings = list(csv.DictReader(handle, delimiter="\t"))
failed = [row for row in findings if row.get("status", "").lower() == "fail"]
if failed:
    raise RuntimeError(
        "Scientific resource validation failed: "
        + "; ".join(str(row.get("check")) for row in failed)
    )

with resource_path.open("r", encoding="utf-8-sig", newline="") as handle:
    records = list(csv.DictReader(handle, delimiter="\t"))
if not records:
    raise RuntimeError(f"No resource-monitor summaries found: {resource_path}")
problems = []
for row in records:
    repeats = int(row["repeat_count"])
    successful = int(row["successful_repeats"])
    peak_ram = float(row["maximum_peak_rss_mb"])
    if repeats != successful:
        problems.append(
            f"{row['stage_name']}: {successful}/{repeats} successful repeats"
        )
    if peak_ram <= 0:
        problems.append(f"{row['stage_name']}: no positive RAM measurement")
if problems:
    raise RuntimeError("Resource monitoring failed: " + "; ".join(problems))

print(f"Validated {len(findings)} scientific checks and {len(records)} stages.")
PY
}

create_review_bundle() {
    local run_root="$1"
    local review_dir="$2"
    local run_tag="$3"
    local bundle_root="${review_dir}/full_onekp_plus_v0_1_14_${run_tag}"
    local archive="${bundle_root}.tar.gz"
    local directory=""

    rm -rf -- "${bundle_root}"
    mkdir -p "${bundle_root}/selected_logs"

    for directory in qc summaries benchmark_summary provenance resource_metrics run_setup; do
        if [[ -d "${run_root}/${directory}" ]]; then
            rsync -a "${run_root}/${directory}/" "${bundle_root}/${directory}/"
        fi
    done

    if [[ -d "${run_root}/logs" ]]; then
        rsync -a \
            --include='*/' \
            --include='*.log' \
            --exclude='*' \
            "${run_root}/logs/" \
            "${bundle_root}/selected_logs/"
    fi

    for path in slurm_job_metadata.tsv slurm_job_record.txt slurm_accounting.tsv; do
        if [[ -f "${run_root}/${path}" ]]; then
            cp "${run_root}/${path}" "${bundle_root}/"
        fi
    done

    tar -czf "${archive}" \
        -C "$(dirname "${bundle_root}")" \
        "$(basename "${bundle_root}")"
    printf '%s\n' "${archive}" > "${run_root}/review_bundle_path.txt"
    log "Compact review bundle: ${archive}"
}

for variable in \
    E3_REPO_ROOT \
    E3_SOURCE_ROOT \
    E3_RESULTS_BASE \
    E3_RUN_ROOT \
    E3_SETUP_DIR \
    E3_REVIEW_DIR \
    E3_THREADS \
    E3_DIAMOND_MEMORY \
    E3_CONDA_ENV \
    E3_MIN_RESULTS_FREE_GIB \
    E3_MIN_SCRATCH_FREE_GIB \
    E3_RUN_TAG; do
    require_variable "${variable}"
done

[[ "${E3_THREADS}" =~ ^[1-9][0-9]*$ ]] || {
    error "E3_THREADS must be a positive integer: ${E3_THREADS}"
    exit 2
}
[[ "${E3_MIN_RESULTS_FREE_GIB}" =~ ^[1-9][0-9]*$ ]] || {
    error "E3_MIN_RESULTS_FREE_GIB must be a positive integer"
    exit 2
}
[[ "${E3_MIN_SCRATCH_FREE_GIB}" =~ ^[1-9][0-9]*$ ]] || {
    error "E3_MIN_SCRATCH_FREE_GIB must be a positive integer"
    exit 2
}
[[ -d "${E3_REPO_ROOT}" ]] || {
    error "Repository root is missing: ${E3_REPO_ROOT}"
    exit 2
}
[[ -d "${E3_SOURCE_ROOT}" ]] || {
    error "Source root is missing: ${E3_SOURCE_ROOT}"
    exit 2
}

mkdir -p "${E3_RUN_ROOT}" "${E3_SETUP_DIR}" "${E3_REVIEW_DIR}"
rm -f "${E3_RUN_ROOT}/workflow_failed.tsv"

if [[ -n "${E3_SCRATCH_BASE:-}" ]]; then
    JOB_SCRATCH="${E3_SCRATCH_BASE%/}/e3_onekp_${SLURM_JOB_ID}"
    REMOVE_SCRATCH_ON_EXIT=1
elif [[ -n "${SLURM_TMPDIR:-}" ]]; then
    JOB_SCRATCH="${SLURM_TMPDIR%/}/e3_onekp_${SLURM_JOB_ID}"
elif [[ -n "${TMPDIR:-}" ]]; then
    JOB_SCRATCH="${TMPDIR%/}/e3_onekp_${SLURM_JOB_ID}"
    REMOVE_SCRATCH_ON_EXIT=1
else
    JOB_SCRATCH="/tmp/${USER}/e3_onekp_${SLURM_JOB_ID}"
    REMOVE_SCRATCH_ON_EXIT=1
fi
mkdir -p "${JOB_SCRATCH}/generic_tmp" "${JOB_SCRATCH}/diamond_tmp"
check_free_space_gib "${E3_RESULTS_BASE}" "${E3_MIN_RESULTS_FREE_GIB}" "persistent results"
check_free_space_gib "${JOB_SCRATCH}" "${E3_MIN_SCRATCH_FREE_GIB}" "job scratch"
export TMPDIR="${JOB_SCRATCH}/generic_tmp"

CURRENT_STAGE="activating Conda environment"
activate_conda_environment "${E3_CONDA_ENV}"

CURRENT_STAGE="checking software"
cd "${E3_REPO_ROOT}"
python -m pip install -e . --no-deps
python --version
diamond version
snakemake --version

cat > "${E3_RUN_ROOT}/slurm_job_metadata.tsv" <<META
field	value
job_id	${SLURM_JOB_ID:-not_available}
job_name	${SLURM_JOB_NAME:-not_available}
node	${SLURMD_NODENAME:-$(hostname)}
account	${SLURM_JOB_ACCOUNT:-barton}
partition	${SLURM_JOB_PARTITION:-general}
cpus	${SLURM_CPUS_PER_TASK:-${E3_THREADS}}
slurm_memory_per_node_mb	${SLURM_MEM_PER_NODE:-not_available}
source_root	${E3_SOURCE_ROOT}
repository	${E3_REPO_ROOT}
results_root	${E3_RUN_ROOT}
scratch	${JOB_SCRATCH}
minimum_results_free_gib	${E3_MIN_RESULTS_FREE_GIB}
minimum_scratch_free_gib	${E3_MIN_SCRATCH_FREE_GIB}
started_at_utc	${JOB_STARTED_UTC}
META

if command -v scontrol >/dev/null 2>&1; then
    scontrol show job -dd "${SLURM_JOB_ID}" > "${E3_RUN_ROOT}/slurm_job_record.txt" || true
fi

CURRENT_STAGE="creating full 1KP+ manifest and configuration"
python -m e3_discovery.cli \
    --verbose \
    --log-file "${E3_SETUP_DIR}/create_cluster_config.log" \
    create-full-cluster-config \
    --source-root "${E3_SOURCE_ROOT}" \
    --repository-root "${E3_REPO_ROOT}" \
    --results-root "${E3_RUN_ROOT}" \
    --output-dir "${E3_SETUP_DIR}" \
    --threads "${E3_THREADS}" \
    --memory-limit "${E3_DIAMOND_MEMORY}" \
    --tmpdir "${JOB_SCRATCH}" \
    > "${E3_SETUP_DIR}/create_cluster_config.json"

CONFIG_PATH="${E3_SETUP_DIR}/full_onekp_plus.cluster.config.yaml"
MANIFEST_PATH="${E3_SETUP_DIR}/full_onekp_plus.cluster.samples.tsv"
[[ -s "${CONFIG_PATH}" ]] || {
    error "Generated configuration is missing: ${CONFIG_PATH}"
    exit 2
}
[[ -s "${MANIFEST_PATH}" ]] || {
    error "Generated manifest is missing: ${MANIFEST_PATH}"
    exit 2
}

CURRENT_STAGE="Snakemake dry run"
export E3_DISCOVERY_CONFIG="${CONFIG_PATH}"
SNAKEMAKE_CONDA_PREFIX="${E3_SNAKEMAKE_CONDA_PREFIX:-${HOME}/.cache/e3_discovery_snakemake_conda}"
mkdir -p "${SNAKEMAKE_CONDA_PREFIX}"
if ! snakemake \
    --snakefile Snakefile \
    --cores "${E3_THREADS}" \
    --use-conda \
    --conda-prefix "${SNAKEMAKE_CONDA_PREFIX}" \
    --dry-run \
    > "${E3_SETUP_DIR}/snakemake_dry_run.log" 2>&1; then
    error "Snakemake dry run failed; complete dry-run log follows."
    cat "${E3_SETUP_DIR}/snakemake_dry_run.log" >&2
    false
fi

CURRENT_STAGE="full 1KP+ Snakemake workflow"
snakemake \
    --snakefile Snakefile \
    --cores "${E3_THREADS}" \
    --use-conda \
    --conda-prefix "${SNAKEMAKE_CONDA_PREFIX}" \
    --rerun-incomplete \
    --printshellcmds \
    --show-failed-logs

CURRENT_STAGE="validating completed result"
validate_completed_result "${E3_RUN_ROOT}"

CURRENT_STAGE="capturing Slurm accounting"
if command -v sacct >/dev/null 2>&1; then
    sacct \
        -j "${SLURM_JOB_ID}" \
        --units=M \
        --parsable2 \
        --format=JobID,JobName,State,Elapsed,TotalCPU,AllocCPUS,ReqMem,MaxRSS,MaxVMSize,ExitCode \
        > "${E3_RUN_ROOT}/slurm_accounting.tsv" || true
fi

CURRENT_STAGE="creating review bundle"
create_review_bundle "${E3_RUN_ROOT}" "${E3_REVIEW_DIR}" "${E3_RUN_TAG}"

touch "${E3_RUN_ROOT}/workflow_complete.ok"
cat >> "${E3_RUN_ROOT}/slurm_job_metadata.tsv" <<META
finished_at_utc	$(date -u +%Y-%m-%dT%H:%M:%SZ)
status	complete
META

REMOVE_SCRATCH_ON_EXIT=1
CURRENT_STAGE="complete"
log "Full 1KP+ workflow completed successfully."
log "Persistent result: ${E3_RUN_ROOT}"
