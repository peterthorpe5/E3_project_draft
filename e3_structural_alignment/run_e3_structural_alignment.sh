#!/usr/bin/env bash
# Run the standalone structural-alignment package using named options only.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
declare -a COMMAND=(e3-structure-align run)

usage() {
    cat <<'EOF'
Usage: run_e3_structural_alignment.sh [named e3-structure-align run options]

Required options:
  --selected-pockets PATH
  --pocket-residue-mappings PATH
  --asset-manifest PATH
  --output-dir PATH

Typical optional controls:
  --usalign-executable PATH
  --tmalign-executable PATH
  --skip-usalign
  --skip-tmalign
  --threads INTEGER
  --distance-threshold-angstrom FLOAT
  --maximum-centroid-distance-angstrom FLOAT
  --minimum-pocket-overlap-fraction FLOAT
  --minimum-global-tm-score FLOAT
  --minimum-group-support-fraction FLOAT
  --resume
  --force

The shell contains no Python source. It validates that the installed package is available and
forwards all named arguments to its production CLI.
EOF
}

if (($# == 0)); then
    usage >&2
    exit 2
fi
case "${1-}" in
    --help|-h)
        usage
        exit 0
        ;;
    --version)
        e3-structure-align --version
        exit 0
        ;;
esac

command -v e3-structure-align >/dev/null || {
    printf 'ERROR: install this package first: python -m pip install -e %s\n' \
        "${SCRIPT_DIR}" >&2
    exit 2
}
COMMAND+=("$@")
exec "${COMMAND[@]}"
