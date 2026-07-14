#!/usr/bin/env bash
#
# Run the E3 Discovery Engine benchmark ladder and/or the inherited 1KP+ run.
#
# The script creates reproducible local manifests and YAML configurations,
# performs defensive preflight checks, runs analyses sequentially with the
# production tantan masking setting, validates each result, and creates a
# compact review bundle. It can detach itself with nohup/caffeinate so the
# terminal may be closed while the work continues.
#
# Recommended sequence:
#   1. ./scripts/run_e3_scaling_and_full.sh --mode ladder --detach
#   2. Review the 10/20/40/60-proteome results.
#   3. ./scripts/run_e3_scaling_and_full.sh --mode full --detach
#
# A single unattended ladder plus full run is also supported:
#   ./scripts/run_e3_scaling_and_full.sh --mode ladder-and-full --detach
#
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "${SCRIPT_PATH}")"

# When installed below <repo>/scripts, the repository is the parent folder.
if [[ -f "${SCRIPT_DIR}/../Snakefile" ]]; then
    DEFAULT_REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    DEFAULT_REPO="/Users/PThorpe001/github_repos/E3_project_draft/e3_discovery_engine"
fi

REPO="${E3_REPO:-${DEFAULT_REPO}}"
SOURCE_ROOT="${E3_SOURCE_ROOT:-/Volumes/One Touch/SSD_back_up_July_2026/Erin_Butterfield_data}"
RESULTS_BASE="${E3_RESULTS_BASE:-/Volumes/One Touch/E3_discovery_engine_results}"
DISCOVERY_ROOT="${SOURCE_ROOT}/Other_things/Denbi/denbi_data/E3_discovery_engine"
BENCHMARK_FASTA_DIR="${SOURCE_ROOT}/Other_things/Denbi/denbi_data/E3_ligase_eukaryote_db"
FULL_FASTA_DIR="${DISCOVERY_ROOT}/files/fasta_files"
SEED_TABLE="${DISCOVERY_ROOT}/files/e3_ligases.csv"

MODE="ladder"
CORES=4
DETACH=0
FOREGROUND=0
RUN_TESTS=0
RUN_TAG="$(date '+%Y%m%d_%H%M%S')"
MIN_FREE_GB_LADDER=20
MIN_FREE_GB_FULL=100
MASTER_LOG=""
CURRENT_STEP="initialisation"

usage() {
    cat <<'EOF'
Usage:
  run_e3_scaling_and_full.sh [options]

Modes:
  --mode ladder           Run 10, 20, 40 and 60-proteome benchmarks.
                          This is the default and the recommended next step.
  --mode full             Run only the inherited 1KP+ dataset.
  --mode ladder-and-full  Run the benchmark ladder and then 1KP+ unattended.

Options:
  --detach                Run under nohup and caffeinate, write a PID file,
                          and return control to the terminal immediately.
  --cores INTEGER         Snakemake/DIAMOND threads. Default: 4.
  --run-tests             Run ./run_tests.sh before analysis.
  --run-tag TEXT          Reuse a fixed tag to resume configurations/runs.
  --repo PATH             Repository root.
  --source-root PATH      Erin_Butterfield_data source root.
  --results-base PATH     External results directory.
  --minimum-ladder-gb N   Required free space for ladder. Default: 20.
  --minimum-full-gb N     Required free space for 1KP+. Default: 100.
  -h, --help              Show this help.

Examples:
  ./scripts/run_e3_scaling_and_full.sh --mode ladder --detach
  ./scripts/run_e3_scaling_and_full.sh --mode full --detach --cores 4
  ./scripts/run_e3_scaling_and_full.sh --mode ladder-and-full --detach

Status after detaching:
  cat  <results-base>/driver_logs/e3_scaling_<tag>.pid
  tail -f <results-base>/driver_logs/e3_scaling_<tag>.log
  ps -p "$(cat <pid-file>)"
EOF
}

log() {
    local message="$1"
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') [INFO] ${message}"
    if [[ -n "${MASTER_LOG}" ]]; then
        printf '%s\n' "${line}" | tee -a "${MASTER_LOG}"
    else
        printf '%s\n' "${line}"
    fi
}

error() {
    local message="$1"
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') [ERROR] ${message}"
    if [[ -n "${MASTER_LOG}" ]]; then
        printf '%s\n' "${line}" | tee -a "${MASTER_LOG}" >&2
    else
        printf '%s\n' "${line}" >&2
    fi
}

die() {
    error "$1"
    exit 2
}

on_error() {
    local code=$?
    error "Failed during: ${CURRENT_STEP} (exit code ${code})."
    [[ -z "${MASTER_LOG}" ]] || error "Driver log: ${MASTER_LOG}"
    exit "${code}"
}

trap on_error ERR
trap 'error "Interrupted during: ${CURRENT_STEP}"; exit 130' INT TERM

absolute_path() {
    python - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

free_gb() {
    python - "$1" <<'PY'
from pathlib import Path
import shutil
import sys
path = Path(sys.argv[1]).expanduser().resolve()
path.mkdir(parents=True, exist_ok=True)
print(shutil.disk_usage(path).free / (1024 ** 3))
PY
}

require_free_space() {
    local required="$1"
    local available
    available="$(free_gb "${RESULTS_BASE}")"
    python - "${available}" "${required}" <<'PY'
import sys
available = float(sys.argv[1])
required = float(sys.argv[2])
if available < required:
    raise SystemExit(
        f"Insufficient free space: {available:.1f} GiB available; "
        f"{required:.1f} GiB required."
    )
print(f"Free-space check passed: {available:.1f} GiB available.")
PY
}

validate_result() {
    local label="$1"
    local root="$2"
    CURRENT_STEP="validating ${label}"

    python - "${label}" "${root}" <<'PY'
"""Validate a completed E3 workflow result."""

import csv
from pathlib import Path
import sys

label = sys.argv[1]
root = Path(sys.argv[2]).expanduser().resolve()

required = [
    root / "duckdb" / "e3_discovery_resource.duckdb",
    root / "qc" / "resource_validation.tsv",
    root / "summaries" / "workflow_key_metrics.tsv",
    root / "benchmark_summary" / "resource_usage_summary.tsv",
    root / "provenance" / "run_manifest.json",
]

missing = [str(path) for path in required if not path.is_file() or path.stat().st_size == 0]
if missing:
    raise RuntimeError(f"{label} is incomplete:\n" + "\n".join(missing))

with required[1].open("r", encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
failed = [row for row in rows if row.get("status", "").lower() != "pass"]
if failed:
    details = "\n".join(
        f"{row.get('check')}: {row.get('status')} {row.get('message', '')}"
        for row in failed
    )
    raise RuntimeError(f"{label} has failed validation checks:\n{details}")

with required[3].open("r", encoding="utf-8-sig", newline="") as handle:
    resource_rows = list(csv.DictReader(handle, delimiter="\t"))
if not resource_rows:
    raise RuntimeError(f"No resource records found for {label}.")

problems = []
for row in resource_rows:
    if int(row["successful_repeats"]) != int(row["repeat_count"]):
        problems.append(f"{row['stage_name']}: incomplete repeats")
    if float(row["maximum_peak_rss_mb"]) <= 0:
        problems.append(f"{row['stage_name']}: no positive peak RAM")
if problems:
    raise RuntimeError(f"{label} resource checks failed:\n" + "\n".join(problems))

print(
    f"{label}: {len(rows)} scientific checks passed and "
    f"{len(resource_rows)} stages have resource measurements."
)
PY
    log "${label} passed validation."
}

create_review_bundle() {
    local label="$1"
    local root="$2"
    local config="$3"
    local manifest="$4"
    local bundle="${RESULTS_BASE}/review_bundles/${label}_${RUN_TAG}"
    local archive="${bundle}.tar.gz"

    CURRENT_STEP="creating ${label} review bundle"
    rm -rf "${bundle}"
    mkdir -p "${bundle}/selected_logs"

    local directory
    for directory in qc summaries benchmark_summary provenance resource_metrics; do
        if [[ -d "${root}/${directory}" ]]; then
            rsync -a "${root}/${directory}/" "${bundle}/${directory}/"
        fi
    done

    if [[ -d "${root}/logs" ]]; then
        rsync -a \
            --include='*/' \
            --include='*.log' \
            --exclude='*' \
            "${root}/logs/" \
            "${bundle}/selected_logs/"
    fi

    cp "${config}" "${bundle}/configuration_used.yaml"
    cp "${manifest}" "${bundle}/samples_used.tsv"

    tar -czf "${archive}" \
        -C "$(dirname "${bundle}")" \
        "$(basename "${bundle}")"

    log "Review bundle: ${archive}"
}

create_manifest_and_config() {
    local label="$1"
    local samples_json="$2"
    local fasta_dir="$3"
    local output_root="$4"
    local config_dir="$5"
    local manifest="${config_dir}/${label}.samples.local.tsv"
    local config="${config_dir}/${label}.config.local.yaml"

    python - \
        "${label}" \
        "${samples_json}" \
        "${fasta_dir}" \
        "${SEED_TABLE}" \
        "${output_root}" \
        "${REPO}" \
        "${CORES}" \
        "${manifest}" \
        "${config}" <<'PY'
"""Create one manifest and production configuration defensively."""

import csv
import json
from pathlib import Path
import re
import sys

import yaml

(
    label,
    samples_json_text,
    fasta_dir_text,
    seed_table_text,
    output_root_text,
    repo_text,
    cores_text,
    manifest_text,
    config_text,
) = sys.argv[1:]

samples_json = Path(samples_json_text).expanduser().resolve()
fasta_dir = Path(fasta_dir_text).expanduser().resolve()
seed_table = Path(seed_table_text).expanduser().resolve()
output_root = Path(output_root_text).expanduser().resolve()
repo = Path(repo_text).expanduser().resolve()
manifest_path = Path(manifest_text).expanduser().resolve()
config_path = Path(config_text).expanduser().resolve()
cores = int(cores_text)

for path in (samples_json, seed_table):
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(path)
if not fasta_dir.is_dir():
    raise NotADirectoryError(fasta_dir)

with samples_json.open("r", encoding="utf-8") as handle:
    payload = json.load(handle)
samples = payload.get("Samples")
if not isinstance(samples, list) or not samples:
    raise ValueError(f"No Samples list in {samples_json}")

os_pattern = re.compile(r"(?:^|\s)OS=(.*?)(?=\sOX=|\s[A-Z]{2}=|$)")
ox_pattern = re.compile(r"(?:^|\s)OX=(\d+)")

rows = []
missing = []
for sample in samples:
    fasta = fasta_dir / f"{sample}.fasta"
    if not fasta.is_file() or fasta.stat().st_size == 0:
        missing.append(str(fasta))
        continue

    species = sample.replace("_", " ")
    taxon_id = ""
    source_database = "inherited_project_FASTA"

    with fasta.open("r", encoding="utf-8", errors="replace") as handle:
        first_header = ""
        for line in handle:
            if line.startswith(">"):
                first_header = line[1:].strip()
                break

    if sample == "onekp_dataset":
        species = "1KP combined transcriptome-derived protein dataset"
        source_database = "1KP inherited combined dataset"
    else:
        os_match = os_pattern.search(first_header)
        ox_match = ox_pattern.search(first_header)
        if os_match:
            species = os_match.group(1).strip()
        if ox_match:
            taxon_id = ox_match.group(1)

    rows.append(
        {
            "sample_id": sample,
            "fasta_path": str(fasta),
            "species": species,
            "taxon_id": taxon_id,
            "proteome_id": "",
            "source_database": source_database,
            "release": "not_recorded",
            "provenance_status": "source_release_to_be_confirmed",
        }
    )

if missing:
    raise FileNotFoundError(
        "Required FASTA files are missing or empty:\n" + "\n".join(missing)
    )

manifest_path.parent.mkdir(parents=True, exist_ok=True)
fieldnames = [
    "sample_id",
    "fasta_path",
    "species",
    "taxon_id",
    "proteome_id",
    "source_database",
    "release",
    "provenance_status",
]
with manifest_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=fieldnames,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)

configuration = {
    "project": {
        "name": f"e3_{label}_tantan",
        "description": (
            f"Production E3 Discovery Engine run for {label}. "
            "Identifies sequence clusters containing at least one previously "
            "identified E3 candidate; cluster membership is not functional proof."
        ),
    },
    "inputs": {
        "samples_tsv": str(manifest_path),
        "e3_seed_table": str(seed_table),
        "e3_seed_column": "entry",
        "identifier_mode": "prefix_sample",
        "compute_input_checksums": True,
    },
    "outputs": {"root": str(output_root)},
    "software": {
        "environment": str((repo / "workflow" / "envs" / "production.yml").resolve())
    },
    "resources": {"threads": cores, "parquet_batch_size": 250000},
    "diamond": {
        "executable": "diamond",
        "path_alias_root": str((repo / ".e3_path_aliases").resolve()),
        "identity_mode": "exact",
        "identity_percent": 50,
        "mutual_cover_percent": 50,
        "clustering_evalue": 0.1,
        "comp_based_stats": 0,
        "memory_limit": "16G",
        "masking": "tantan",
        "cluster_steps": [],
        "extra_args": [],
    },
    "thresholds": {
        "minimum_percent_identity": 50,
        "minimum_representative_coverage": 50,
        "minimum_member_coverage": 50,
        "minimum_bitscore": 20,
        "maximum_evalue": 1.0e-10,
    },
    "benchmarking": {"repeats": 1},
}

with config_path.open("w", encoding="utf-8") as handle:
    yaml.safe_dump(configuration, handle, sort_keys=False)

print(f"Created manifest: {manifest_path}")
print(f"Created config:   {config_path}")
print(f"Samples:          {len(rows)}")
print(f"Output root:      {output_root}")
PY

    printf '%s\t%s\n' "${manifest}" "${config}"
}

run_one() {
    local label="$1"
    local samples_json="$2"
    local fasta_dir="$3"
    local minimum_free="$4"
    local config_dir="${REPO}/config/generated_runs/${RUN_TAG}"
    local output_root="${RESULTS_BASE}/${label}_tantan_${RUN_TAG}"
    local generated manifest config

    CURRENT_STEP="preflight for ${label}"
    require_free_space "${minimum_free}"

    mkdir -p "${config_dir}"
    generated="$(create_manifest_and_config \
        "${label}" \
        "${samples_json}" \
        "${fasta_dir}" \
        "${output_root}" \
        "${config_dir}")"
    manifest="$(printf '%s\n' "${generated}" | tail -1 | cut -f1)"
    config="$(printf '%s\n' "${generated}" | tail -1 | cut -f2)"

    if [[ -s "${output_root}/qc/resource_validation.tsv" ]]; then
        if validate_result "${label}" "${output_root}"; then
            log "${label} already completed; analysis was not rerun."
            create_review_bundle "${label}" "${output_root}" "${config}" "${manifest}"
            return
        fi
    fi

    CURRENT_STEP="dry-run ${label}"
    log "Dry-running ${label}."
    (
        cd "${REPO}"
        export E3_DISCOVERY_CONFIG="${config}"
        snakemake \
            --snakefile Snakefile \
            --cores "${CORES}" \
            --use-conda \
            --dry-run
    ) 2>&1 | tee -a "${MASTER_LOG}"

    CURRENT_STEP="run ${label}"
    log "Starting ${label}: ${output_root}"
    (
        cd "${REPO}"
        ./run_workflow.sh "${config}" "${CORES}"
    ) 2>&1 | tee -a "${MASTER_LOG}"

    validate_result "${label}" "${output_root}"
    create_review_bundle "${label}" "${output_root}" "${config}" "${manifest}"
}

# Preserve original arguments so --detach can relaunch safely.
ORIGINAL_ARGS=("$@")

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --mode)
            [[ "$#" -ge 2 ]] || die "--mode requires a value."
            MODE="$2"
            shift 2
            ;;
        --detach)
            DETACH=1
            shift
            ;;
        --foreground)
            FOREGROUND=1
            shift
            ;;
        --cores)
            [[ "$#" -ge 2 ]] || die "--cores requires an integer."
            CORES="$2"
            shift 2
            ;;
        --run-tests)
            RUN_TESTS=1
            shift
            ;;
        --run-tag)
            [[ "$#" -ge 2 ]] || die "--run-tag requires text."
            RUN_TAG="$2"
            shift 2
            ;;
        --repo)
            [[ "$#" -ge 2 ]] || die "--repo requires a path."
            REPO="$2"
            shift 2
            ;;
        --source-root)
            [[ "$#" -ge 2 ]] || die "--source-root requires a path."
            SOURCE_ROOT="$2"
            shift 2
            ;;
        --results-base)
            [[ "$#" -ge 2 ]] || die "--results-base requires a path."
            RESULTS_BASE="$2"
            shift 2
            ;;
        --minimum-ladder-gb)
            [[ "$#" -ge 2 ]] || die "--minimum-ladder-gb requires a number."
            MIN_FREE_GB_LADDER="$2"
            shift 2
            ;;
        --minimum-full-gb)
            [[ "$#" -ge 2 ]] || die "--minimum-full-gb requires a number."
            MIN_FREE_GB_FULL="$2"
            shift 2
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

case "${MODE}" in
    ladder|full|ladder-and-full)
        ;;
    *)
        die "Invalid mode: ${MODE}"
        ;;
esac

[[ "${CORES}" =~ ^[1-9][0-9]*$ ]] || die "Cores must be a positive integer."
[[ "${RUN_TAG}" =~ ^[A-Za-z0-9._-]+$ ]] || die "Unsafe run tag: ${RUN_TAG}"

# Resolve paths after command-line overrides.
REPO="$(absolute_path "${REPO}")"
SOURCE_ROOT="$(absolute_path "${SOURCE_ROOT}")"
RESULTS_BASE="$(absolute_path "${RESULTS_BASE}")"
DISCOVERY_ROOT="${SOURCE_ROOT}/Other_things/Denbi/denbi_data/E3_discovery_engine"
BENCHMARK_FASTA_DIR="${SOURCE_ROOT}/Other_things/Denbi/denbi_data/E3_ligase_eukaryote_db"
FULL_FASTA_DIR="${DISCOVERY_ROOT}/files/fasta_files"
SEED_TABLE="${DISCOVERY_ROOT}/files/e3_ligases.csv"

mkdir -p "${RESULTS_BASE}/driver_logs"
MASTER_LOG="${RESULTS_BASE}/driver_logs/e3_scaling_${RUN_TAG}.log"
PID_FILE="${RESULTS_BASE}/driver_logs/e3_scaling_${RUN_TAG}.pid"

if [[ "${DETACH}" -eq 1 && "${FOREGROUND}" -eq 0 ]]; then
    # Rebuild arguments without --detach, then add the internal foreground flag.
    RELAUNCH_ARGS=()
    skip_next=0
    for arg in "${ORIGINAL_ARGS[@]}"; do
        if [[ "${arg}" == "--detach" ]]; then
            continue
        fi
        RELAUNCH_ARGS+=("${arg}")
    done
    RELAUNCH_ARGS+=("--foreground")

    launcher=(bash "${SCRIPT_PATH}" "${RELAUNCH_ARGS[@]}")
    if command -v caffeinate >/dev/null 2>&1; then
        launcher=(caffeinate -dimsu "${launcher[@]}")
    fi

    nohup "${launcher[@]}" > "${MASTER_LOG}" 2>&1 < /dev/null &
    pid=$!
    printf '%s\n' "${pid}" > "${PID_FILE}"

    printf 'Started detached E3 run.\n'
    printf 'PID: %s\n' "${pid}"
    printf 'Log: %s\n' "${MASTER_LOG}"
    printf 'PID file: %s\n' "${PID_FILE}"
    printf 'Follow progress with:\n  tail -f %q\n' "${MASTER_LOG}"
    exit 0
fi

touch "${MASTER_LOG}"
log "Mode: ${MODE}"
log "Repository: ${REPO}"
log "Source root: ${SOURCE_ROOT}"
log "Results base: ${RESULTS_BASE}"
log "Run tag: ${RUN_TAG}"
log "Cores: ${CORES}"

[[ -f "${REPO}/Snakefile" ]] || die "Snakefile not found below repository: ${REPO}"
[[ -x "${REPO}/run_workflow.sh" ]] || die "run_workflow.sh is missing or not executable."
[[ -f "${SEED_TABLE}" ]] || die "E3 seed table not found: ${SEED_TABLE}"
command -v python >/dev/null 2>&1 || die "Python is not available."
command -v snakemake >/dev/null 2>&1 || die "Snakemake is not available."
command -v rsync >/dev/null 2>&1 || die "rsync is not available."

if [[ "${RUN_TESTS}" -eq 1 ]]; then
    CURRENT_STEP="package tests"
    log "Running package tests."
    (
        cd "${REPO}"
        ./run_tests.sh
    ) 2>&1 | tee -a "${MASTER_LOG}"
fi

if [[ "${MODE}" == "ladder" || "${MODE}" == "ladder-and-full" ]]; then
    for count in 10 20 40 60; do
        samples_json="${DISCOVERY_ROOT}/benchmarking/test_${count}_proteomes/samples.json"
        [[ -f "${samples_json}" ]] || die "Missing inherited sample list: ${samples_json}"
        run_one \
            "benchmark_${count}_proteomes" \
            "${samples_json}" \
            "${BENCHMARK_FASTA_DIR}" \
            "${MIN_FREE_GB_LADDER}"
    done
fi

if [[ "${MODE}" == "full" || "${MODE}" == "ladder-and-full" ]]; then
    samples_json="${DISCOVERY_ROOT}/samples.json"
    [[ -f "${samples_json}" ]] || die "Missing inherited full sample list: ${samples_json}"
    [[ -s "${FULL_FASTA_DIR}/onekp_dataset.fasta" ]] || \
        die "The 1KP FASTA is missing or empty: ${FULL_FASTA_DIR}/onekp_dataset.fasta"
    run_one \
        "full_onekp_plus" \
        "${samples_json}" \
        "${FULL_FASTA_DIR}" \
        "${MIN_FREE_GB_FULL}"
fi

CURRENT_STEP="complete"
log "Requested E3 analyses completed successfully."
log "Driver log: ${MASTER_LOG}"
