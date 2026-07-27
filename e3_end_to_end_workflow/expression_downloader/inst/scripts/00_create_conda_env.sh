#!/usr/bin/env bash
set -euo pipefail

# Create the recommended conda environment for E3AtlasDuckplyr.
# Uses mamba when available, otherwise falls back to conda.

ENV_FILE="${1:-envs/e3_atlas_duckplyr.yml}"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Cannot find environment file: ${ENV_FILE}" >&2
    echo "Run this from the unpacked package directory, or pass the path to the environment YAML." >&2
    exit 1
fi

if command -v mamba >/dev/null 2>&1; then
    mamba env create -f "${ENV_FILE}"
else
    conda env create -f "${ENV_FILE}"
fi

echo ""
echo "Environment created. Activate with:"
echo "  conda activate e3_atlas_duckplyr"
