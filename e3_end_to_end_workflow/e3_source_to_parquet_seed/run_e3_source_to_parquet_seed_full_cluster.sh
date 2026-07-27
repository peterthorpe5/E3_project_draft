#!/usr/bin/env bash
# Run e3_source_to_parquet_seed from inherited source files through the
# cluster-native Parquet/DuckDB resource and the validated cluster-level
# candidate-evidence resource.
#
# The script is safe by default:
#   * it creates timestamped output directories;
#   * it does not overwrite the inherited source files;
#   * it runs the package test suite before production work;
#   * it submits itself to Slurm when launched from a login node;
#   * it writes persistent logs, provenance and a completion marker.
#
# Typical use from the repository root:
#   ./run_e3_source_to_parquet_seed_full_cluster.sh
#
# Submit without waiting for completion:
#   ./run_e3_source_to_parquet_seed_full_cluster.sh --no-wait
#
# Use an Expression Atlas DuckDB during the curated-resource build:
#   ./run_e3_source_to_parquet_seed_full_cluster.sh \
#       --expression-duckdb /absolute/path/to/e3_expression.duckdb

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$({
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
})"
REPO_ROOT="${SCRIPT_DIR}"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename -- "${BASH_SOURCE[0]}")"

PROJECT_ROOT="/home/pthorpe001/data/2026_E3_protac/E3_PROTAC_curated"
DISCOVERY_DUCKDB="/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results/full_onekp_plus_v0_1_14_20260715_100551/duckdb/e3_discovery_resource.duckdb"
EXPRESSION_DUCKDB=""
CONDA_ENV="e3_discovery"
RUN_TAG="$(date +%Y%m%d_%H%M%S)"
SOURCE_DERIVED_DIR=""
CANDIDATE_OUTPUT_DIR=""

ACCOUNT="barton"
PARTITION="general"
CPUS=8
SLURM_MEMORY="64G"
WALLTIME="1-00:00:00"

RUN_TESTS="true"
CALCULATE_SOURCE_SHA256="true"
WAIT_FOR_JOB="true"
RUN_NOW="false"
POLL_SECONDS=60

usage() {
    cat <<'USAGE'
Usage:
  ./run_e3_source_to_parquet_seed_full_cluster.sh [options]

Data and output options:
  --project-root PATH          Permanent E3_PROTAC_curated directory.
  --discovery-duckdb PATH      Completed discovery-engine DuckDB.
  --expression-duckdb PATH     Optional Expression Atlas DuckDB.
  --source-derived-dir PATH    Output for source-preserving Parquet/DuckDB.
  --candidate-output-dir PATH  Output for cluster candidate evidence.
  --run-tag TEXT               Stable identifier used in default output paths.
  --conda-env NAME             Conda environment. Default: e3_discovery.

Slurm options:
  --account NAME               Default: barton.
  --partition NAME             Default: general.
  --cpus INTEGER               Default: 8.
  --memory VALUE               Default: 64G.
  --time VALUE                 Default: 1-00:00:00.
  --poll-seconds INTEGER       Wait-loop interval. Default: 60.

Execution options:
  --skip-tests                 Do not run the package release test suite.
  --skip-source-sha256         Skip hashing the source discovery DuckDB.
  --no-wait                    Submit the Slurm job and return immediately.
  --run-now                    Run in the current shell instead of submitting.
  -h, --help                   Show this help.

Default outputs are new timestamped directories beneath:
  PROJECT_ROOT/rebuilds/source_to_parquet_seed_RUN_TAG/

The script never deletes or overwrites inherited source files.
USAGE
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root)
            PROJECT_ROOT="${2:?}"
            shift 2
            ;;
        --discovery-duckdb)
            DISCOVERY_DUCKDB="${2:?}"
            shift 2
            ;;
        --expression-duckdb)
            EXPRESSION_DUCKDB="${2:?}"
            shift 2
            ;;
        --source-derived-dir)
            SOURCE_DERIVED_DIR="${2:?}"
            shift 2
            ;;
        --candidate-output-dir)
            CANDIDATE_OUTPUT_DIR="${2:?}"
            shift 2
            ;;
        --run-tag)
            RUN_TAG="${2:?}"
            shift 2
            ;;
        --conda-env)
            CONDA_ENV="${2:?}"
            shift 2
            ;;
        --account)
            ACCOUNT="${2:?}"
            shift 2
            ;;
        --partition)
            PARTITION="${2:?}"
            shift 2
            ;;
        --cpus)
            CPUS="${2:?}"
            shift 2
            ;;
        --memory)
            SLURM_MEMORY="${2:?}"
            shift 2
            ;;
        --time)
            WALLTIME="${2:?}"
            shift 2
            ;;
        --poll-seconds)
            POLL_SECONDS="${2:?}"
            shift 2
            ;;
        --skip-tests)
            RUN_TESTS="false"
            shift
            ;;
        --skip-source-sha256)
            CALCULATE_SOURCE_SHA256="false"
            shift
            ;;
        --no-wait)
            WAIT_FOR_JOB="false"
            shift
            ;;
        --run-now)
            RUN_NOW="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

[[ "${RUN_TAG}" =~ ^[A-Za-z0-9._-]+$ ]] || \
    die "--run-tag may contain only letters, digits, '.', '_' and '-'"
[[ "${CPUS}" =~ ^[1-9][0-9]*$ ]] || \
    die "--cpus must be a positive integer"
[[ "${POLL_SECONDS}" =~ ^[1-9][0-9]*$ ]] || \
    die "--poll-seconds must be a positive integer"

PROJECT_ROOT="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${PROJECT_ROOT}")"
DISCOVERY_DUCKDB="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${DISCOVERY_DUCKDB}")"

if [[ -n "${EXPRESSION_DUCKDB}" ]]; then
    EXPRESSION_DUCKDB="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "${EXPRESSION_DUCKDB}")"
fi

RUN_ROOT="${PROJECT_ROOT}/rebuilds/source_to_parquet_seed_${RUN_TAG}"
SOURCE_DERIVED_DIR="${SOURCE_DERIVED_DIR:-${RUN_ROOT}/source_resource}"
CANDIDATE_OUTPUT_DIR="${CANDIDATE_OUTPUT_DIR:-${RUN_ROOT}/candidate_evidence_resource}"
DRIVER_LOG_DIR="${RUN_ROOT}/driver_logs"

mkdir -p "${DRIVER_LOG_DIR}"

wait_for_slurm_job() {
    local job_id="$1"

    printf 'Waiting for Slurm job %s...\n' "${job_id}"
    while squeue -h -j "${job_id}" 2>/dev/null | grep -q .; do
        printf '%s | job %s still active\n' \
            "$(date --iso-8601=seconds 2>/dev/null || date)" \
            "${job_id}"
        sleep "${POLL_SECONDS}"
    done

    printf 'Job %s is no longer in squeue.\n' "${job_id}"
}

if [[ "${RUN_NOW}" != "true" && -z "${SLURM_JOB_ID:-}" ]]; then
    command -v sbatch >/dev/null 2>&1 || die "sbatch is not available"

    worker_args=(
        --run-now
        --project-root "${PROJECT_ROOT}"
        --discovery-duckdb "${DISCOVERY_DUCKDB}"
        --source-derived-dir "${SOURCE_DERIVED_DIR}"
        --candidate-output-dir "${CANDIDATE_OUTPUT_DIR}"
        --run-tag "${RUN_TAG}"
        --conda-env "${CONDA_ENV}"
        --account "${ACCOUNT}"
        --partition "${PARTITION}"
        --cpus "${CPUS}"
        --memory "${SLURM_MEMORY}"
        --time "${WALLTIME}"
        --poll-seconds "${POLL_SECONDS}"
    )

    [[ -n "${EXPRESSION_DUCKDB}" ]] && \
        worker_args+=(--expression-duckdb "${EXPRESSION_DUCKDB}")
    [[ "${RUN_TESTS}" == "false" ]] && worker_args+=(--skip-tests)
    [[ "${CALCULATE_SOURCE_SHA256}" == "false" ]] && \
        worker_args+=(--skip-source-sha256)

    JOB_ID="$(
        sbatch \
            --parsable \
            --job-name="e3_parquet_seed" \
            --account="${ACCOUNT}" \
            --partition="${PARTITION}" \
            --nodes=1 \
            --ntasks=1 \
            --cpus-per-task="${CPUS}" \
            --mem="${SLURM_MEMORY}" \
            --time="${WALLTIME}" \
            --output="${DRIVER_LOG_DIR}/slurm-%j.out" \
            --error="${DRIVER_LOG_DIR}/slurm-%j.err" \
            "${SCRIPT_PATH}" \
            "${worker_args[@]}"
    )"
    JOB_ID="${JOB_ID%%;*}"

    printf '%s\n' "${JOB_ID}" > "${DRIVER_LOG_DIR}/slurm_job_id.txt"
    printf 'Submitted Slurm job: %s\n' "${JOB_ID}"
    printf 'Run root: %s\n' "${RUN_ROOT}"
    printf 'Standard output: %s\n' \
        "${DRIVER_LOG_DIR}/slurm-${JOB_ID}.out"

    if [[ "${WAIT_FOR_JOB}" == "true" ]]; then
        wait_for_slurm_job "${JOB_ID}"
        sacct \
            -j "${JOB_ID}" \
            --units=G \
            --parsable2 \
            --format=JobID,JobName,State,Elapsed,TotalCPU,AllocCPUS,ReqMem,MaxRSS,MaxVMSize,ExitCode \
            > "${DRIVER_LOG_DIR}/slurm_accounting.tsv" || true
        cat "${DRIVER_LOG_DIR}/slurm_accounting.tsv" || true

        [[ -f "${RUN_ROOT}/workflow_complete.ok" ]] || \
            die "Slurm job ended without workflow_complete.ok: ${RUN_ROOT}"
    fi

    exit 0
fi

LOG_PATH="${DRIVER_LOG_DIR}/run_e3_source_to_parquet_seed_full.log"
exec > >(tee -a "${LOG_PATH}") 2>&1

trap 'printf "FAILED at line %s: %s\n" "${LINENO}" "${BASH_COMMAND}" >&2' ERR

printf 'Started: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
printf 'Host: %s\n' "$(hostname)"
printf 'Slurm job: %s\n' "${SLURM_JOB_ID:-not_submitted}"
printf 'Repository: %s\n' "${REPO_ROOT}"
printf 'Project root: %s\n' "${PROJECT_ROOT}"
printf 'Discovery DuckDB: %s\n' "${DISCOVERY_DUCKDB}"
printf 'Expression DuckDB: %s\n' "${EXPRESSION_DUCKDB:-not_supplied}"
printf 'Source-resource output: %s\n' "${SOURCE_DERIVED_DIR}"
printf 'Candidate-evidence output: %s\n' "${CANDIDATE_OUTPUT_DIR}"
printf 'Conda environment: %s\n' "${CONDA_ENV}"

cd "${REPO_ROOT}"

[[ -f "${REPO_ROOT}/run_e3_seed_pipeline.sh" ]] || \
    die "Missing run_e3_seed_pipeline.sh in ${REPO_ROOT}"
[[ -f "${REPO_ROOT}/run_e3_candidate_evidence.sh" ]] || \
    die "Missing run_e3_candidate_evidence.sh in ${REPO_ROOT}"
[[ -d "${PROJECT_ROOT}/raw_inherited_selected" ]] || \
    die "Missing raw_inherited_selected below ${PROJECT_ROOT}"
[[ -f "${DISCOVERY_DUCKDB}" ]] || \
    die "Missing discovery DuckDB: ${DISCOVERY_DUCKDB}"
[[ -z "${EXPRESSION_DUCKDB}" || -f "${EXPRESSION_DUCKDB}" ]] || \
    die "Missing Expression DuckDB: ${EXPRESSION_DUCKDB}"

for output_dir in "${SOURCE_DERIVED_DIR}" "${CANDIDATE_OUTPUT_DIR}"; do
    if [[ -d "${output_dir}" ]] && \
       [[ -n "$(find "${output_dir}" -mindepth 1 -print -quit)" ]]; then
        die "Output directory is not empty: ${output_dir}"
    fi
done

command -v conda >/dev/null 2>&1 || die "conda is not available"

printf 'Git commit: '
git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || printf 'not-a-git-checkout\n'
printf 'Git status:\n'
git -C "${REPO_ROOT}" status --short 2>/dev/null || true

conda run \
    --no-capture-output \
    -n "${CONDA_ENV}" \
    python -m pip install --no-deps --editable "${REPO_ROOT}"

if [[ "${RUN_TESTS}" == "true" ]]; then
    conda run \
        --no-capture-output \
        -n "${CONDA_ENV}" \
        bash "${REPO_ROOT}/run_tests.sh"
fi

printf '\nBuilding source-preserving Parquet and cluster-native DuckDB...\n'
conda run \
    --no-capture-output \
    -n "${CONDA_ENV}" \
    bash "${REPO_ROOT}/run_e3_seed_pipeline.sh" \
    "${PROJECT_ROOT}" \
    "${EXPRESSION_DUCKDB}" \
    "${SOURCE_DERIVED_DIR}"

printf '\nBuilding validated cluster-level candidate evidence...\n'
candidate_command=(
    bash "${REPO_ROOT}/run_e3_candidate_evidence.sh"
    "${DISCOVERY_DUCKDB}"
    "${CANDIDATE_OUTPUT_DIR}"
    --conda-env "${CONDA_ENV}"
)
[[ "${CALCULATE_SOURCE_SHA256}" == "false" ]] && \
    candidate_command+=(--skip-source-sha256)
"${candidate_command[@]}"

required_outputs=(
    "${SOURCE_DERIVED_DIR}/duckdb/e3_protac_resource.duckdb"
    "${SOURCE_DERIVED_DIR}/docs/FILES_USED_AND_CURATED_VIEWS.md"
    "${CANDIDATE_OUTPUT_DIR}/candidate_evidence/e3_cluster_candidate_evidence.tsv"
    "${CANDIDATE_OUTPUT_DIR}/candidate_evidence/e3_cluster_candidate_evidence.parquet"
    "${CANDIDATE_OUTPUT_DIR}/duckdb/e3_candidate_evidence.duckdb"
    "${CANDIDATE_OUTPUT_DIR}/qc/e3_cluster_candidate_evidence_validation.tsv"
    "${CANDIDATE_OUTPUT_DIR}/provenance/e3_cluster_candidate_evidence_manifest.json"
)

for required_output in "${required_outputs[@]}"; do
    [[ -s "${required_output}" ]] || \
        die "Required output is missing or empty: ${required_output}"
done

conda run \
    --no-capture-output \
    -n "${CONDA_ENV}" \
    python - \
    "${CANDIDATE_OUTPUT_DIR}/qc/e3_cluster_candidate_evidence_validation.tsv" \
    "${CANDIDATE_OUTPUT_DIR}/provenance/e3_cluster_candidate_evidence_manifest.json" <<'PY'
"""Verify the final candidate-evidence validation contract."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

validation_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])

with validation_path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))

if not rows:
    raise SystemExit(f"Validation table is empty: {validation_path}")

status_column = next(
    (name for name in rows[0] if name.lower() == "status"),
    None,
)
if status_column is None:
    raise SystemExit("Validation table has no status column")

failures = [row for row in rows if row[status_column] != "PASS"]
if failures:
    raise SystemExit(f"Candidate-evidence checks failed: {failures}")

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest["validation_pass_count"] != manifest["validation_check_count"]:
    raise SystemExit("Manifest validation counts do not reconcile")
if manifest["candidate_row_count"] <= 0:
    raise SystemExit("Candidate-evidence table contains no rows")

print(
    "Candidate-evidence validation passed: "
    f"{manifest['validation_pass_count']} checks; "
    f"{manifest['candidate_row_count']} clusters"
)
PY

{
    printf 'completed_at\t%s\n' \
        "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf 'repository\t%s\n' "${REPO_ROOT}"
    printf 'git_commit\t%s\n' \
        "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || printf unknown)"
    printf 'project_root\t%s\n' "${PROJECT_ROOT}"
    printf 'discovery_duckdb\t%s\n' "${DISCOVERY_DUCKDB}"
    printf 'source_derived_dir\t%s\n' "${SOURCE_DERIVED_DIR}"
    printf 'candidate_output_dir\t%s\n' "${CANDIDATE_OUTPUT_DIR}"
} > "${RUN_ROOT}/workflow_complete.ok"

printf '\nCompleted successfully.\n'
du -sh "${SOURCE_DERIVED_DIR}" "${CANDIDATE_OUTPUT_DIR}"
printf 'Completion marker: %s\n' "${RUN_ROOT}/workflow_complete.ok"
printf 'Finished: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
