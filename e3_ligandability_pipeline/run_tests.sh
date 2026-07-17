#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd -P
)"
cd "${PACKAGE_ROOT}"

python -m pycodestyle \
    --max-line-length=88 \
    e3ligandability \
    scripts \
    tests

python -m unittest discover -s tests -v

for script in \
    run_e3_ligandability.sh \
    run_legacy_regression.sh \
    scripts/submit_e3_ligandability_slurm.sh \
    scripts/slurm_e3_ligandability_job.sh
do
    bash -n "${script}"
done
