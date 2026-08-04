#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PACKAGE_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
cd -- "${PACKAGE_DIR}"

python -m compileall -q inst/python tests/python
python -m pycodestyle --max-line-length=100 inst/python tests/python
python -m pydocstyle --convention=google \
  --add-ignore=D104,D105,D107,D202 inst/python
python -m coverage erase
python -m coverage run --branch --source=inst/python \
  -m unittest discover -s tests/python -p 'test_*.py' -v
python -m coverage report --show-missing --fail-under=90
bash -n inst/scripts/*.sh

printf 'All Expression Atlas Python quality gates passed.\n'
