#!/usr/bin/env bash

set -euo pipefail

DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="/home/pthorpe001/data/2026_E3_protac/expression_downloader"

Rscript "${REPO_DIR}/inst/scripts/06_create_duckdb_views.R" \
  --output_dir="${DATA_DIR}" \
  --duckdb_path="${DATA_DIR}/e3_expression.duckdb"
