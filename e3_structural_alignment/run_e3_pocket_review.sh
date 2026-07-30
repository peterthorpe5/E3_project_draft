#!/usr/bin/env bash
# Generate self-contained ranked pocket-review HTML reports using named options.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec python -m e3structalign.review_cli "$@"
