#!/usr/bin/env bash
# Run the structure-guided chemistry unit, integration and quality gates.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "${SCRIPT_DIR}"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
unset PYTEST_ADDOPTS

python -m compileall -q src tests
python -m pycodestyle src tests --max-line-length=100
python -m pydocstyle src tests
python -m coverage erase
python -m coverage run --branch -m pytest -q "${SCRIPT_DIR}/tests"
python -m coverage report --fail-under=95
bash -n \
    run_e3_structure_guided_chemistry.sh \
    run_tests.sh \
    scripts/prepare_expanded_candidate_manifest.sh \
    scripts/run_dundee_expanded_top200_v0_2_1.sh \
    scripts/run_dundee_full_universe_v0_3_0.sh \
    scripts/validate_dundee_full_universe_v0_3_1.slurm.sh \
    scripts/submit_e3_structure_guided_chemistry_slurm.sh \
    scripts/slurm_e3_structure_guided_chemistry_job.sh

printf 'All e3_structure_guided_chemistry quality gates passed.\n'
