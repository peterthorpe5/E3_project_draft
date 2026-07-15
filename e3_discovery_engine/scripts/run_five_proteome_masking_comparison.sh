#!/usr/bin/env bash
#
# Run and validate the matched five-proteome masking comparison.
#
# This driver runs the existing tantan and no-masking Snakemake
# configurations sequentially, validates each completed result, and creates
# a compact comparison bundle. Snakemake safely resumes partially completed
# runs and does nothing for stages that are already complete.
#
# Default use from the repository root:
#
#   ./scripts/run_five_proteome_masking_comparison.sh
#
# After both analyses have already completed:
#
#   ./scripts/run_five_proteome_masking_comparison.sh --bundle-only
#
# Optional:
#
#   ./scripts/run_five_proteome_masking_comparison.sh \
#       --tantan-config config/config.five_proteome_tantan.local.yaml \
#       --nomask-config config/config.five_proteome_nomask.local.yaml \
#       --cores 4 \
#       --run-tests
#

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TANTAN_CONFIG="${REPO_ROOT}/config/config.five_proteome_tantan.local.yaml"
NOMASK_CONFIG="${REPO_ROOT}/config/config.five_proteome_nomask.local.yaml"
CORES=4
RUN_TESTS=0
BUNDLE_ONLY=0
DRY_RUN_ONLY=0
BUNDLE_DIR=""

MASTER_LOG=""
CURRENT_STEP="initialisation"


usage() {
    cat <<'EOF'
Usage:
  run_five_proteome_masking_comparison.sh [options]

Options:
  --tantan-config PATH  Tantan configuration file.
  --nomask-config PATH  No-masking configuration file.
  --cores INTEGER       Number of Snakemake cores. Default: 4.
  --run-tests           Run the ordinary package test suite first.
  --bundle-only         Do not invoke Snakemake; validate and bundle existing runs.
  --dry-run-only        Perform Snakemake dry runs but do not execute analyses.
  --bundle-dir PATH     Explicit comparison-bundle directory.
  -h, --help            Show this help.

The two configurations must be identical except for:
  * project name;
  * project description;
  * output root;
  * diamond.masking.

The tantan configuration must use masking: tantan.
The no-masking configuration must use masking: none.
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
    local exit_code=$?
    error "Failed during: ${CURRENT_STEP} (exit code ${exit_code})."
    if [[ -n "${MASTER_LOG}" ]]; then
        error "Driver log: ${MASTER_LOG}"
    fi
    exit "${exit_code}"
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


yaml_value() {
    local config_path="$1"
    local dotted_key="$2"

    python - "${config_path}" "${dotted_key}" <<'PY'
from pathlib import Path
import sys

import yaml

path = Path(sys.argv[1]).expanduser().resolve()
keys = sys.argv[2].split(".")

with path.open("r", encoding="utf-8") as handle:
    value = yaml.safe_load(handle)

for key in keys:
    value = value[key]

print(value)
PY
}


validate_configuration_pair() {
    local tantan_path="$1"
    local nomask_path="$2"

    python - "${tantan_path}" "${nomask_path}" <<'PY'
"""Validate that two masking configurations form a controlled comparison."""

import copy
from pathlib import Path
import sys

import yaml


def load(path_text: str) -> tuple[Path, dict]:
    """Load one YAML configuration."""
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Configuration is not a mapping: {path}")

    return path, data


tantan_path, tantan = load(sys.argv[1])
nomask_path, nomask = load(sys.argv[2])

tantan_mask = str(tantan["diamond"]["masking"]).lower()
nomask_mask = str(nomask["diamond"]["masking"]).lower()

if tantan_mask != "tantan":
    raise ValueError(
        f"Tantan configuration uses masking={tantan_mask!r}, not 'tantan': "
        f"{tantan_path}"
    )

if nomask_mask != "none":
    raise ValueError(
        f"No-masking configuration uses masking={nomask_mask!r}, not 'none': "
        f"{nomask_path}"
    )

tantan_root = Path(tantan["outputs"]["root"]).expanduser().resolve()
nomask_root = Path(nomask["outputs"]["root"]).expanduser().resolve()

if tantan_root == nomask_root:
    raise ValueError("The two configurations use the same output root.")

allowed_differences = (
    ("project", "name"),
    ("project", "description"),
    ("outputs", "root"),
    ("diamond", "masking"),
)


def normalise(configuration: dict) -> dict:
    """Remove fields intentionally different between comparison runs."""
    result = copy.deepcopy(configuration)

    for parent, child in allowed_differences:
        if parent in result and isinstance(result[parent], dict):
            result[parent].pop(child, None)

    return result


if normalise(tantan) != normalise(nomask):
    raise ValueError(
        "Configurations differ in fields other than project metadata, "
        "output root, and masking mode. Refusing an uncontrolled comparison."
    )

print("Configuration-pair validation passed.")
print(f"Tantan output: {tantan_root}")
print(f"No-mask output: {nomask_root}")
PY
}


validate_completed_run() {
    local label="$1"
    local root="$2"

    CURRENT_STEP="validating ${label} run"

    python - "${label}" "${root}" <<'PY'
"""Validate one completed five-proteome workflow result."""

import csv
from pathlib import Path
import sys


label = sys.argv[1]
root = Path(sys.argv[2]).expanduser().resolve()

required = {
    "DuckDB resource": root / "duckdb" / "e3_discovery_resource.duckdb",
    "validation table": root / "qc" / "resource_validation.tsv",
    "key metrics": root / "summaries" / "workflow_key_metrics.tsv",
    "realignment summary": (
        root / "summaries" / "realignment_content_summary.tsv"
    ),
    "sample E3 summary": root / "summaries" / "sample_e3_summary.tsv",
    "resource summary": (
        root / "benchmark_summary" / "resource_usage_summary.tsv"
    ),
    "resource records": (
        root / "benchmark_summary" / "resource_usage_records.tsv"
    ),
    "RAM PNG": root / "benchmark_summary" / "peak_ram_by_stage.png",
    "RAM PDF": root / "benchmark_summary" / "peak_ram_by_stage.pdf",
    "run manifest": root / "provenance" / "run_manifest.json",
}

missing = [
    f"{description}: {path}"
    for description, path in required.items()
    if not path.is_file() or path.stat().st_size == 0
]

if missing:
    raise RuntimeError(
        f"{label} run is incomplete:\n" + "\n".join(missing)
    )

validation_path = required["validation table"]

with validation_path.open(
    "r",
    encoding="utf-8-sig",
    newline="",
) as handle:
    validation_rows = list(csv.DictReader(handle, delimiter="\t"))

if not validation_rows:
    raise RuntimeError(f"No validation rows found: {validation_path}")

failed_checks = [
    row
    for row in validation_rows
    if str(row.get("status", "")).strip().lower() != "pass"
]

if failed_checks:
    details = "\n".join(
        f"{row.get('check')}: {row.get('status')} "
        f"({row.get('message', '')})"
        for row in failed_checks
    )
    raise RuntimeError(
        f"{label} run contains failed validation checks:\n{details}"
    )

resource_path = required["resource summary"]

with resource_path.open(
    "r",
    encoding="utf-8-sig",
    newline="",
) as handle:
    resource_rows = list(csv.DictReader(handle, delimiter="\t"))

if not resource_rows:
    raise RuntimeError(f"No resource rows found: {resource_path}")

resource_failures = []

for row in resource_rows:
    stage = row["stage_name"]
    repeats = int(row["repeat_count"])
    successful = int(row["successful_repeats"])
    peak_ram = float(row["maximum_peak_rss_mb"])

    if successful != repeats:
        resource_failures.append(
            f"{stage}: {successful}/{repeats} repeats succeeded"
        )

    if peak_ram <= 0:
        resource_failures.append(
            f"{stage}: peak RAM was not positive ({peak_ram})"
        )

if resource_failures:
    raise RuntimeError(
        f"{label} resource-monitor validation failed:\n"
        + "\n".join(resource_failures)
    )

print(
    f"{label}: validation passed "
    f"({len(validation_rows)} scientific checks; "
    f"{len(resource_rows)} monitored stages)."
)
PY

    log "${label} run passed scientific and resource validation."
}


run_workflow_pair_member() {
    local label="$1"
    local config_path="$2"
    local root="$3"

    CURRENT_STEP="dry-running ${label} workflow"
    log "Dry-running ${label} workflow."

    (
        cd "${REPO_ROOT}"
        export E3_DISCOVERY_CONFIG="${config_path}"
        snakemake \
            --snakefile Snakefile \
            --cores "${CORES}" \
            --use-conda \
            --dry-run
    ) 2>&1 | tee -a "${MASTER_LOG}"

    if [[ "${DRY_RUN_ONLY}" -eq 1 ]]; then
        return
    fi

    CURRENT_STEP="running ${label} workflow"
    log "Running ${label} workflow sequentially."

    (
        cd "${REPO_ROOT}"
        ./run_workflow.sh "${config_path}" "${CORES}"
    ) 2>&1 | tee -a "${MASTER_LOG}"

    validate_completed_run "${label}" "${root}"
}


copy_review_material() {
    local label="$1"
    local root="$2"
    local config_path="$3"
    local destination="${BUNDLE_DIR}/${label}"
    local directory

    mkdir -p "${destination}/selected_logs"

    for directory in \
        qc \
        summaries \
        benchmark_summary \
        provenance \
        resource_metrics; do

        if [[ -d "${root}/${directory}" ]]; then
            rsync -a \
                "${root}/${directory}/" \
                "${destination}/${directory}/"
        fi
    done

    if [[ -d "${root}/logs" ]]; then
        rsync -a \
            --include='*/' \
            --include='*.log' \
            --exclude='*' \
            "${root}/logs/" \
            "${destination}/selected_logs/"
    fi

    cp "${config_path}" "${destination}/configuration_used.yaml"
}


write_comparison_tables() {
    local tantan_root="$1"
    local nomask_root="$2"

    python - \
        "${tantan_root}" \
        "${nomask_root}" \
        "${BUNDLE_DIR}" <<'PY'
"""Create direct metric and resource comparisons for two completed runs."""

import csv
from pathlib import Path
import sys


tantan_root = Path(sys.argv[1]).expanduser().resolve()
nomask_root = Path(sys.argv[2]).expanduser().resolve()
output_dir = Path(sys.argv[3]).expanduser().resolve()


def read_key_value_table(path: Path) -> dict[str, float]:
    """Read a metric/value TSV as numerical values."""
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return {
            row["metric"]: float(row["value"])
            for row in rows
        }


def read_resource_table(path: Path) -> dict[str, dict[str, str]]:
    """Read the resource summary indexed by stage."""
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        return {
            row["stage_name"]: row
            for row in csv.DictReader(handle, delimiter="\t")
        }


tantan_metrics = read_key_value_table(
    tantan_root / "summaries" / "workflow_key_metrics.tsv"
)
nomask_metrics = read_key_value_table(
    nomask_root / "summaries" / "workflow_key_metrics.tsv"
)

metric_output = output_dir / "masking_key_metrics_comparison.tsv"

with metric_output.open(
    "w",
    encoding="utf-8",
    newline="",
) as handle:
    writer = csv.writer(
        handle,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writerow(
        [
            "metric",
            "tantan_value",
            "nomask_value",
            "nomask_minus_tantan",
            "percent_change_from_tantan",
        ]
    )

    for metric in sorted(set(tantan_metrics) | set(nomask_metrics)):
        tantan_value = tantan_metrics.get(metric)
        nomask_value = nomask_metrics.get(metric)

        if tantan_value is None or nomask_value is None:
            writer.writerow(
                [
                    metric,
                    "" if tantan_value is None else tantan_value,
                    "" if nomask_value is None else nomask_value,
                    "",
                    "",
                ]
            )
            continue

        difference = nomask_value - tantan_value
        percent_change = (
            ""
            if tantan_value == 0
            else 100.0 * difference / tantan_value
        )

        writer.writerow(
            [
                metric,
                tantan_value,
                nomask_value,
                difference,
                percent_change,
            ]
        )

tantan_resources = read_resource_table(
    tantan_root / "benchmark_summary" / "resource_usage_summary.tsv"
)
nomask_resources = read_resource_table(
    nomask_root / "benchmark_summary" / "resource_usage_summary.tsv"
)

resource_output = output_dir / "masking_resource_comparison.tsv"

with resource_output.open(
    "w",
    encoding="utf-8",
    newline="",
) as handle:
    writer = csv.writer(
        handle,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writerow(
        [
            "stage_name",
            "tantan_wall_seconds",
            "nomask_wall_seconds",
            "wall_seconds_difference",
            "tantan_peak_rss_mb",
            "nomask_peak_rss_mb",
            "peak_rss_mb_difference",
        ]
    )

    for stage in sorted(set(tantan_resources) | set(nomask_resources)):
        tantan = tantan_resources.get(stage)
        nomask = nomask_resources.get(stage)

        if tantan is None or nomask is None:
            writer.writerow(
                [
                    stage,
                    "" if tantan is None else tantan["mean_wall_seconds"],
                    "" if nomask is None else nomask["mean_wall_seconds"],
                    "",
                    "" if tantan is None else tantan["maximum_peak_rss_mb"],
                    "" if nomask is None else nomask["maximum_peak_rss_mb"],
                    "",
                ]
            )
            continue

        tantan_wall = float(tantan["mean_wall_seconds"])
        nomask_wall = float(nomask["mean_wall_seconds"])
        tantan_ram = float(tantan["maximum_peak_rss_mb"])
        nomask_ram = float(nomask["maximum_peak_rss_mb"])

        writer.writerow(
            [
                stage,
                tantan_wall,
                nomask_wall,
                nomask_wall - tantan_wall,
                tantan_ram,
                nomask_ram,
                nomask_ram - tantan_ram,
            ]
        )

print(f"Wrote: {metric_output}")
print(f"Wrote: {resource_output}")
PY
}


create_bundle() {
    local tantan_root="$1"
    local nomask_root="$2"
    local manifest_path
    local archive_path

    CURRENT_STEP="creating comparison bundle"
    log "Creating compact comparison bundle."

    if [[ -e "${BUNDLE_DIR}" ]]; then
        die "Bundle directory already exists: ${BUNDLE_DIR}"
    fi

    mkdir -p "${BUNDLE_DIR}"

    copy_review_material \
        "tantan" \
        "${tantan_root}" \
        "${TANTAN_CONFIG}"

    copy_review_material \
        "nomask" \
        "${nomask_root}" \
        "${NOMASK_CONFIG}"

    manifest_path="$(yaml_value "${TANTAN_CONFIG}" "inputs.samples_tsv")"
    manifest_path="$(absolute_path "${manifest_path}")"

    if [[ -f "${manifest_path}" ]]; then
        cp \
            "${manifest_path}" \
            "${BUNDLE_DIR}/five_proteome_samples_used.tsv"
    fi

    if [[ -f "${REPO_ROOT}/workflow/envs/production.yml" ]]; then
        cp \
            "${REPO_ROOT}/workflow/envs/production.yml" \
            "${BUNDLE_DIR}/production_environment.yml"
    fi

    if command -v git >/dev/null 2>&1 &&
        git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree \
            >/dev/null 2>&1; then

        git -C "${REPO_ROOT}" rev-parse HEAD \
            > "${BUNDLE_DIR}/git_commit.txt"

        git -C "${REPO_ROOT}" status --short \
            > "${BUNDLE_DIR}/git_status.txt"
    fi

    cp "${MASTER_LOG}" "${BUNDLE_DIR}/comparison_driver.log"

    write_comparison_tables "${tantan_root}" "${nomask_root}"

    archive_path="${BUNDLE_DIR}.tar.gz"

    tar -czf "${archive_path}" \
        -C "$(dirname "${BUNDLE_DIR}")" \
        "$(basename "${BUNDLE_DIR}")"

    log "Comparison bundle: ${BUNDLE_DIR}"
    log "Compressed bundle: ${archive_path}"
    du -sh "${archive_path}" | tee -a "${MASTER_LOG}"
}


while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --tantan-config)
            [[ "$#" -ge 2 ]] || die "--tantan-config requires a path."
            TANTAN_CONFIG="$2"
            shift 2
            ;;
        --nomask-config)
            [[ "$#" -ge 2 ]] || die "--nomask-config requires a path."
            NOMASK_CONFIG="$2"
            shift 2
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
        --bundle-only)
            BUNDLE_ONLY=1
            shift
            ;;
        --dry-run-only)
            DRY_RUN_ONLY=1
            shift
            ;;
        --bundle-dir)
            [[ "$#" -ge 2 ]] || die "--bundle-dir requires a path."
            BUNDLE_DIR="$2"
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


[[ "${CORES}" =~ ^[1-9][0-9]*$ ]] ||
    die "Cores must be a positive integer: ${CORES}"

TANTAN_CONFIG="$(absolute_path "${TANTAN_CONFIG}")"
NOMASK_CONFIG="$(absolute_path "${NOMASK_CONFIG}")"

[[ -f "${TANTAN_CONFIG}" ]] ||
    die "Tantan configuration does not exist: ${TANTAN_CONFIG}"

[[ -f "${NOMASK_CONFIG}" ]] ||
    die "No-masking configuration does not exist: ${NOMASK_CONFIG}"

command -v python >/dev/null 2>&1 ||
    die "Python is not available in the active environment."

command -v snakemake >/dev/null 2>&1 ||
    die "Snakemake is not available in the active environment."

command -v rsync >/dev/null 2>&1 ||
    die "rsync is not available."

validate_configuration_pair "${TANTAN_CONFIG}" "${NOMASK_CONFIG}"

TANTAN_ROOT="$(yaml_value "${TANTAN_CONFIG}" "outputs.root")"
NOMASK_ROOT="$(yaml_value "${NOMASK_CONFIG}" "outputs.root")"
TANTAN_ROOT="$(absolute_path "${TANTAN_ROOT}")"
NOMASK_ROOT="$(absolute_path "${NOMASK_ROOT}")"

RESULTS_BASE="$(
    python - "${TANTAN_ROOT}" "${NOMASK_ROOT}" <<'PY'
from pathlib import Path
import os
import sys

first = Path(sys.argv[1]).resolve()
second = Path(sys.argv[2]).resolve()
print(Path(os.path.commonpath([first.parent, second.parent])))
PY
)"

RUN_TAG="$(date '+%Y%m%d_%H%M%S')"

if [[ -z "${BUNDLE_DIR}" ]]; then
    BUNDLE_DIR="${RESULTS_BASE}/five_proteome_masking_comparison_${RUN_TAG}"
else
    BUNDLE_DIR="$(absolute_path "${BUNDLE_DIR}")"
fi

LOG_DIR="${RESULTS_BASE}/comparison_driver_logs"
mkdir -p "${LOG_DIR}"
MASTER_LOG="${LOG_DIR}/masking_comparison_${RUN_TAG}.log"
touch "${MASTER_LOG}"

log "Repository: ${REPO_ROOT}"
log "Tantan configuration: ${TANTAN_CONFIG}"
log "No-mask configuration: ${NOMASK_CONFIG}"
log "Tantan output: ${TANTAN_ROOT}"
log "No-mask output: ${NOMASK_ROOT}"
log "Cores: ${CORES}"
log "Driver log: ${MASTER_LOG}"

if [[ "${RUN_TESTS}" -eq 1 ]]; then
    CURRENT_STEP="running package tests"
    log "Running ordinary package tests."

    (
        cd "${REPO_ROOT}"
        ./run_tests.sh
    ) 2>&1 | tee -a "${MASTER_LOG}"
fi

if [[ "${BUNDLE_ONLY}" -eq 0 ]]; then
    run_workflow_pair_member \
        "tantan" \
        "${TANTAN_CONFIG}" \
        "${TANTAN_ROOT}"

    run_workflow_pair_member \
        "nomask" \
        "${NOMASK_CONFIG}" \
        "${NOMASK_ROOT}"
else
    log "Bundle-only mode: Snakemake execution was skipped."
fi

if [[ "${DRY_RUN_ONLY}" -eq 1 ]]; then
    log "Dry-run-only mode completed."
    exit 0
fi

validate_completed_run "tantan" "${TANTAN_ROOT}"
validate_completed_run "nomask" "${NOMASK_ROOT}"

create_bundle "${TANTAN_ROOT}" "${NOMASK_ROOT}"

CURRENT_STEP="complete"
log "Five-proteome masking comparison completed successfully."
