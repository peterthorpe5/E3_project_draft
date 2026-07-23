#!/usr/bin/env bash
# Launch the tested Python application with named options.

set -Eeuo pipefail

RESOURCE_DUCKDB=""
RESOURCE_PARQUET=""
RESOURCE_RUN_DIR=""
EXPRESSION_DUCKDB=""
MAX_ROWS="1000"
HOST="127.0.0.1"
PORT="8501"
HEADLESS="false"
VALIDATE_ONLY="false"

usage() {
    cat <<'EOF'
Usage: run_e3_python_app.sh RESOURCE_OPTION [options]

Options:
  --resource-duckdb PATH     Integrated/source-first DuckDB.
  --resource-parquet PATH    Single candidate master-results Parquet.
  --resource-run-dir PATH    Current workflow run containing stage Parquets.
  --expression-duckdb PATH   Optional Expression Atlas DuckDB.
  --max-rows INTEGER         Hard preview/search row cap (default: 1000).
  --host HOST                Bind address (default: 127.0.0.1).
  --port INTEGER             TCP port (default: 8501).
  --headless                 Start Streamlit without opening a browser.
  --validate-only            Validate configuration without starting a server.
  --help                     Show this help text.
EOF
}

while (($#)); do
    case "$1" in
        --resource-duckdb) RESOURCE_DUCKDB="$2"; shift 2 ;;
        --resource-parquet) RESOURCE_PARQUET="$2"; shift 2 ;;
        --resource-run-dir) RESOURCE_RUN_DIR="$2"; shift 2 ;;
        --expression-duckdb) EXPRESSION_DUCKDB="$2"; shift 2 ;;
        --max-rows) MAX_ROWS="$2"; shift 2 ;;
        --host) HOST="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --headless) HEADLESS="true"; shift ;;
        --validate-only) VALIDATE_ONLY="true"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

SOURCE_COUNT="0"
[[ -n "${RESOURCE_DUCKDB}" ]] && SOURCE_COUNT="$((SOURCE_COUNT + 1))"
[[ -n "${RESOURCE_PARQUET}" ]] && SOURCE_COUNT="$((SOURCE_COUNT + 1))"
[[ -n "${RESOURCE_RUN_DIR}" ]] && SOURCE_COUNT="$((SOURCE_COUNT + 1))"
[[ "${SOURCE_COUNT}" == "1" ]] || {
    printf 'ERROR: choose exactly one resource source option.\n' >&2
    exit 2
}
COMMAND=(e3-python-app --max-rows "${MAX_ROWS}"
    --host "${HOST}" --port "${PORT}")
[[ -n "${RESOURCE_DUCKDB}" ]] && COMMAND+=(--resource-duckdb "${RESOURCE_DUCKDB}")
[[ -n "${RESOURCE_PARQUET}" ]] && COMMAND+=(--resource-parquet "${RESOURCE_PARQUET}")
[[ -n "${RESOURCE_RUN_DIR}" ]] && COMMAND+=(--resource-run-dir "${RESOURCE_RUN_DIR}")
[[ -n "${EXPRESSION_DUCKDB}" ]] && COMMAND+=(--expression-duckdb "${EXPRESSION_DUCKDB}")
[[ "${HEADLESS}" == "true" ]] && COMMAND+=(--headless)
[[ "${VALIDATE_ONLY}" == "true" ]] && COMMAND+=(--validate-only)
printf 'Command:'; printf ' %q' "${COMMAND[@]}"; printf '\n'
"${COMMAND[@]}"
