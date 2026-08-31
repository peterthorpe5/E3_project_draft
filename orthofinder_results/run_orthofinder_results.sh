#!/usr/bin/env bash
set -euo pipefail

CONDA_ENV=""
PYTHON_EXECUTABLE="python"
PACKAGE_ARGS=()

while (($#)); do
    case "$1" in
        --conda-env)
            [[ $# -ge 2 ]] || { echo "ERROR: --conda-env requires a value." >&2; exit 2; }
            CONDA_ENV=$2
            shift 2
            ;;
        --python-executable)
            [[ $# -ge 2 ]] || { echo "ERROR: --python-executable requires a value." >&2; exit 2; }
            PYTHON_EXECUTABLE=$2
            shift 2
            ;;
        --)
            shift
            PACKAGE_ARGS+=("$@")
            break
            ;;
        *)
            PACKAGE_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -n "$CONDA_ENV" ]]; then
    command -v conda >/dev/null 2>&1 || {
        echo "ERROR: conda is required for --conda-env ${CONDA_ENV}." >&2
        exit 2
    }
    exec conda run --no-capture-output --name "$CONDA_ENV" \
        "$PYTHON_EXECUTABLE" -m orthofinder_results "${PACKAGE_ARGS[@]}"
fi

exec "$PYTHON_EXECUTABLE" -m orthofinder_results "${PACKAGE_ARGS[@]}"
