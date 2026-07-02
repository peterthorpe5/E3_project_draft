#!/usr/bin/env bash
set -euo pipefail

DOWNLOADED_FILES_TSV=""
OUTPUT_DIR="../analysis/expression_atlas_python"
FORCE_IMPORT="false"
CHUNK_ROWS="250000"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --downloaded_files_tsv=*) DOWNLOADED_FILES_TSV="${1#*=}"; shift ;;
    --downloaded_files_tsv) DOWNLOADED_FILES_TSV="$2"; shift 2 ;;
    --output_dir=*) OUTPUT_DIR="${1#*=}"; shift ;;
    --output_dir) OUTPUT_DIR="$2"; shift 2 ;;
    --force_import=*) FORCE_IMPORT="${1#*=}"; shift ;;
    --force_import) FORCE_IMPORT="$2"; shift 2 ;;
    --chunk_rows=*) CHUNK_ROWS="${1#*=}"; shift ;;
    --chunk_rows) CHUNK_ROWS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${DOWNLOADED_FILES_TSV}" ]]; then
  DOWNLOADED_FILES_TSV="${OUTPUT_DIR}/manifests/atlas_downloaded_files.tsv"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

python "${PKG_DIR}/inst/python/import_expression_to_parquet.py" \
  --downloaded_files_tsv "${DOWNLOADED_FILES_TSV}" \
  --output_dir "${OUTPUT_DIR}" \
  --force_import "${FORCE_IMPORT}" \
  --chunk_rows "${CHUNK_ROWS}"
