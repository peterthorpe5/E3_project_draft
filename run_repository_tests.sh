#!/usr/bin/env bash
# Validate repository-root entry points without embedding implementation code.

set -Eeuo pipefail

readonly REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

python -m unittest discover \
    --start-directory "${REPOSITORY_ROOT}/tests" \
    --pattern 'test_*.py' \
    --verbose
bash -n \
    "${REPOSITORY_ROOT}/run_e3_pipeline.sh" \
    "${REPOSITORY_ROOT}/run_e3_pipeline_fresh.sh" \
    "${REPOSITORY_ROOT}/expression_downloader/run_clean_rebuild_from_existing.sh" \
    "${REPOSITORY_ROOT}/expression_downloader/run_python_first_then_R.sh" \
    "${REPOSITORY_ROOT}/e3_structure_guided_chemistry/run_e3_structure_guided_chemistry.sh" \
    "${REPOSITORY_ROOT}/e3_structure_guided_chemistry/run_tests.sh" \
    "${REPOSITORY_ROOT}/e3_end_to_end_workflow/submit_e3_controller_slurm.sh" \
    "${REPOSITORY_ROOT}/e3_end_to_end_workflow/scripts/slurm_e3_controller_job.sh"
