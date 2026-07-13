#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_INPUT="${1:-${SCRIPT_DIR}/config/config.yaml}"
CORES="${2:-4}"

if [[ ! -f "${CONFIG_INPUT}" ]]; then
  echo "ERROR: configuration file does not exist: ${CONFIG_INPUT}" >&2
  exit 2
fi
if ! [[ "${CORES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: cores must be a positive integer: ${CORES}" >&2
  exit 2
fi
if ! command -v snakemake >/dev/null 2>&1; then
  echo "ERROR: snakemake is not available in the active environment." >&2
  exit 2
fi

export E3_DISCOVERY_CONFIG
E3_DISCOVERY_CONFIG="$(
  python -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' \
    "${CONFIG_INPUT}"
)"

cd "${SCRIPT_DIR}"

snakemake \
  --snakefile Snakefile \
  --cores "${CORES}" \
  --use-conda \
  --rerun-incomplete \
  --printshellcmds \
  --show-failed-logs
