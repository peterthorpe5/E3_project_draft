#!/usr/bin/env bash
# Show status and useful paths for a submitted full 1KP+ Slurm job.

set -Eeuo pipefail
IFS=$'\n\t'

RESULTS_BASE="/home/pthorpe001/data/2026_E3_protac/e3_discovery_engine_results"
JOB_ID=""
TAIL_LINES=60
FOLLOW=0

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/check_full_onekp_slurm.sh [--job-id ID] [options]

Options:
  --job-id ID          Slurm job ID. If omitted, use the latest job_info.tsv.
  --results-base PATH  Persistent result base.
  --tail-lines N       Number of output lines to display. Default: 60.
  --follow             Follow the Slurm standard-output log.
  -h, --help           Show this help.
USAGE
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 2
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --job-id) JOB_ID="${2:?}"; shift 2 ;;
        --results-base) RESULTS_BASE="${2:?}"; shift 2 ;;
        --tail-lines) TAIL_LINES="${2:?}"; shift 2 ;;
        --follow) FOLLOW=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ "${TAIL_LINES}" =~ ^[1-9][0-9]*$ ]] || die "--tail-lines must be positive"

LATEST_INFO="$(
    find "${RESULTS_BASE}/slurm_logs" \
        -type f \
        -name job_info.tsv \
        -print 2>/dev/null \
        | xargs -r ls -t \
        | head -1
)"

if [[ -z "${LATEST_INFO}" ]]; then
    die "No full-run job_info.tsv found below ${RESULTS_BASE}/slurm_logs"
fi

field_value() {
    local field="$1"
    awk -F '\t' -v key="${field}" '$1 == key {print $2; exit}' "${LATEST_INFO}"
}

if [[ -z "${JOB_ID}" ]]; then
    JOB_ID="$(field_value job_id)"
fi

RUN_ROOT="$(field_value results_root)"
STDOUT="$(field_value stdout)"
STDERR="$(field_value stderr)"

printf 'Job ID:       %s\n' "${JOB_ID}"
printf 'Result root:  %s\n' "${RUN_ROOT}"
printf 'Stdout:       %s\n' "${STDOUT}"
printf 'Stderr:       %s\n' "${STDERR}"

if command -v squeue >/dev/null 2>&1; then
    printf '\nCurrent queue state:\n'
    squeue -j "${JOB_ID}" -o '%.18i %.12P %.30j %.10T %.12M %.12l %.5D %R' || true
fi

if command -v sacct >/dev/null 2>&1; then
    printf '\nAccounting state:\n'
    sacct \
        -j "${JOB_ID}" \
        --units=M \
        --format=JobID,State,Elapsed,TotalCPU,AllocCPUS,MaxRSS,ExitCode \
        || true
fi

if [[ -f "${STDOUT}" ]]; then
    printf '\nLatest standard output:\n'
    if [[ "${FOLLOW}" -eq 1 ]]; then
        tail -n "${TAIL_LINES}" -f "${STDOUT}"
    else
        tail -n "${TAIL_LINES}" "${STDOUT}"
    fi
else
    printf '\nStandard-output log has not been created yet.\n'
fi

if [[ -f "${STDERR}" && -s "${STDERR}" ]]; then
    printf '\nLatest standard error:\n'
    tail -n "${TAIL_LINES}" "${STDERR}"
fi

if [[ -f "${RUN_ROOT}/workflow_complete.ok" ]]; then
    printf '\nStatus: complete\n'
    if [[ -f "${RUN_ROOT}/review_bundle_path.txt" ]]; then
        printf 'Review bundle: %s\n' "$(cat "${RUN_ROOT}/review_bundle_path.txt")"
    fi
elif [[ -f "${RUN_ROOT}/workflow_failed.tsv" ]]; then
    printf '\nStatus: failed\n'
    column -t -s $'\t' "${RUN_ROOT}/workflow_failed.tsv" || cat "${RUN_ROOT}/workflow_failed.tsv"
else
    printf '\nStatus: queued or running\n'
fi
