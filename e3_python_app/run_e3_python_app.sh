#!/usr/bin/env bash
# Launch the tested Python application with named options.

set -Eeuo pipefail

RESOURCE_DUCKDB=""
EXPRESSION_DUCKDB=""
MAX_ROWS="1000"
HOST="127.0.0.1"
PORT="8501"
HEADLESS="false"
VALIDATE_ONLY="false"

usage() {
    cat <<'EOF'
Usage: run_e3_python_app.sh --resource-duckdb PATH [options]

Options:
  --resource-duckdb PATH     Required integrated/source-first DuckDB.
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

[[ -n "${RESOURCE_DUCKDB}" ]] || { printf 'ERROR: --resource-duckdb is required.\n' >&2; exit 2; }
COMMAND=(e3-python-app --resource-duckdb "${RESOURCE_DUCKDB}" --max-rows "${MAX_ROWS}"
    --host "${HOST}" --port "${PORT}")
[[ -n "${EXPRESSION_DUCKDB}" ]] && COMMAND+=(--expression-duckdb "${EXPRESSION_DUCKDB}")
[[ "${HEADLESS}" == "true" ]] && COMMAND+=(--headless)
[[ "${VALIDATE_ONLY}" == "true" ]] && COMMAND+=(--validate-only)
printf 'Command:'; printf ' %q' "${COMMAND[@]}"; printf '\n'
"${COMMAND[@]}"

