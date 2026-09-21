#!/usr/bin/env bash
# Launch the managed E3 Python application from its systemd environment.

set -Eeuo pipefail

readonly APP_EXECUTABLE="/opt/e3-python-app/venv/bin/e3-python-app"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 2
}

require_file() {
    local label=$1
    local path=$2
    [[ -f "${path}" ]] || fail "${label} is not a file: ${path}"
}

require_directory() {
    local label=$1
    local path=$2
    [[ -d "${path}" ]] || fail "${label} is not a directory: ${path}"
}

main() {
    [[ -x "${APP_EXECUTABLE}" ]] || fail "Application executable is missing."
    : "${E3_RESOURCE_DUCKDB:?E3_RESOURCE_DUCKDB is required}"
    : "${E3_APP_HOST:=127.0.0.1}"
    : "${E3_APP_PORT:=8501}"
    : "${E3_MAX_TABLE_ROWS:=1000}"

    require_file "E3 resource DuckDB" "${E3_RESOURCE_DUCKDB}"
    local command=(
        "${APP_EXECUTABLE}"
        --resource-duckdb "${E3_RESOURCE_DUCKDB}"
        --max-rows "${E3_MAX_TABLE_ROWS}"
        --host "${E3_APP_HOST}"
        --port "${E3_APP_PORT}"
        --headless
    )

    if [[ -n "${E3_EXPRESSION_DUCKDB:-}" ]]; then
        require_file "Expression DuckDB" "${E3_EXPRESSION_DUCKDB}"
        command+=(--expression-duckdb "${E3_EXPRESSION_DUCKDB}")
    fi
    if [[ -n "${E3_POCKET_REVIEW_DIR:-}" ]]; then
        require_directory "Plant pocket-review bundle" "${E3_POCKET_REVIEW_DIR}"
        command+=(--pocket-review-dir "${E3_POCKET_REVIEW_DIR}")
    fi
    if [[ -n "${E3_HUMAN_PLANT_REVIEW_DIR:-}" ]]; then
        require_directory \
            "Human-and-plant pocket-review bundle" \
            "${E3_HUMAN_PLANT_REVIEW_DIR}"
        command+=(--human-plant-review-dir "${E3_HUMAN_PLANT_REVIEW_DIR}")
    fi
    if [[ -n "${E3_TAXONOMY_MAP:-}" ]]; then
        require_file "Taxonomy mapping" "${E3_TAXONOMY_MAP}"
        command+=(--taxonomy-map "${E3_TAXONOMY_MAP}")
    fi

    exec "${command[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
