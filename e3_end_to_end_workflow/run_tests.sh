#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SYNTHETIC_TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/e3_workflow_tests.XXXXXX")"
SYNTHETIC_CONFIG="$(mktemp "${SCRIPT_DIR}/config/.synthetic_runtime.XXXXXX.yaml")"
SYNTHETIC_RUN_ROOT="${SYNTHETIC_TEST_ROOT}/synthetic_e2e_v0_7_0"
FINAL_DRY_RUN_LOG=""

cleanup() {
    [[ -z "${FINAL_DRY_RUN_LOG}" ]] || rm -f -- "${FINAL_DRY_RUN_LOG}"
    rm -f -- "${SYNTHETIC_CONFIG}"
    case "${SYNTHETIC_TEST_ROOT}" in
        "${TMPDIR:-/tmp}"/e3_workflow_tests.*)
            rm -rf -- "${SYNTHETIC_TEST_ROOT}"
            ;;
        *)
            printf 'WARNING: refusing to remove unexpected test root: %s\n' \
                "${SYNTHETIC_TEST_ROOT}" >&2
            ;;
    esac
}
trap cleanup EXIT

sed \
    "s|^  output_root: ../test_runs$|  output_root: ${SYNTHETIC_TEST_ROOT}|" \
    "${SCRIPT_DIR}/config/synthetic.yaml" > "${SYNTHETIC_CONFIG}"
grep -Fq "  output_root: ${SYNTHETIC_TEST_ROOT}" "${SYNTHETIC_CONFIG}"

cd "${SCRIPT_DIR}"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${TMPDIR:-/tmp}/e3_workflow_cache_${UID}}"
mkdir -p -- "${XDG_CACHE_HOME}"
unset PYTEST_ADDOPTS
python -m compileall -q src tests
python -m pycodestyle src tests --max-line-length=100
python -m pydocstyle src/e3workflow
python -m coverage erase
python -m coverage run --branch -m pytest -q "${SCRIPT_DIR}/tests"
python -m coverage report --fail-under=90
bash -n \
    run_e3_end_to_end.sh \
    submit_e3_end_to_end.sh \
    submit_e3_controller_slurm.sh \
    scripts/slurm_e3_controller_job.sh \
    run_tests.sh
if command -v snakemake >/dev/null 2>&1; then
    snakemake --snakefile workflow/Snakefile --configfile "${SYNTHETIC_CONFIG}" --lint
    ./run_e3_end_to_end.sh --config "${SYNTHETIC_CONFIG}" --dry-run -- --nolock
    ./run_e3_end_to_end.sh \
        --config "${SYNTHETIC_CONFIG}" \
        --force-stage 00_inputs \
        --threads 4 \
        -- \
        --nolock
    test -s "${SYNTHETIC_RUN_ROOT}/reports/e3_workflow_summary.html"
    test -s "${SYNTHETIC_RUN_ROOT}/reports/report_manifest.json"
    grep -q "SYNTHETIC TEST RUN" \
        "${SYNTHETIC_RUN_ROOT}/reports/e3_workflow_summary.html"
    ./run_e3_end_to_end.sh \
        --config "${SYNTHETIC_CONFIG}" \
        --start-at 04_orthofinder \
        --stop-after 05_orthology \
        --threads 4 \
        -- --nolock
    ./run_e3_end_to_end.sh \
        --config "${SYNTHETIC_CONFIG}" \
        --resume \
        --threads 4 \
        -- \
        --nolock
    FINAL_DRY_RUN_LOG="$(mktemp "${TMPDIR:-/tmp}/e3_workflow_dry_run.XXXXXX.log")"
    ./run_e3_end_to_end.sh \
        --config "${SYNTHETIC_CONFIG}" \
        --dry-run \
        -- \
        --nolock 2>&1 | tee "${FINAL_DRY_RUN_LOG}"
    grep -q "Nothing to be done" "${FINAL_DRY_RUN_LOG}"
fi
printf 'All e3_end_to_end_workflow quality gates passed.\n'
