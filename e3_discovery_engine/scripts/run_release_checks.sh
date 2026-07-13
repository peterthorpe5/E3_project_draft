#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

python -m compileall -q src tests
python -m pycodestyle src tests --max-line-length=88
python -m unittest discover -s tests -v
python -m coverage erase
python -m coverage run --source=src/e3_discovery -m unittest discover -s tests
python -m coverage report --show-missing

for required in \
  README.md \
  CHANGELOG.md \
  docs/METHODS.md \
  docs/SCIENTIFIC_INTERPRETATION.md \
  docs/DATA_DICTIONARY.md \
  docs/BENCHMARK_PROTOCOL.md \
  docs/DATA_SOURCES.md \
  docs/OPERATIONS_RUNBOOK.md \
  docs/LEGACY_METHOD_LIMITATIONS.md \
  docs/RELEASE_CHECKLIST.md \
  docs/TESTING.md \
  docs/PACKAGE_FILE_REGISTER.md \
  docs/LEGACY_AUDIT_EVIDENCE_REGISTER.md; do
  test -s "${required}"
done

echo "Release checks completed successfully."
