#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR="analysis/expression_atlas"
FORCE_DOWNLOAD="false"
TIMEOUT_SECONDS="30"
RETRIES="2"
REQUIRE_EXPRESSION_MATRIX="true"
EXPRESSION_FILE_TYPES="tpms,fpkms"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output_dir=*)
      OUTPUT_DIR="${1#*=}"
      shift
      ;;
    --force_download=*)
      FORCE_DOWNLOAD="${1#*=}"
      shift
      ;;
    --timeout_seconds=*)
      TIMEOUT_SECONDS="${1#*=}"
      shift
      ;;
    --retries=*)
      RETRIES="${1#*=}"
      shift
      ;;
    --require_expression_matrix=*)
      REQUIRE_EXPRESSION_MATRIX="${1#*=}"
      shift
      ;;
    --expression_file_types=*)
      EXPRESSION_FILE_TYPES="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

python inst/python/download_atlas_files.py \
  --ftp_manifest_tsv="${OUTPUT_DIR}/manifests/atlas_ftp_manifest.tsv" \
  --checked_manifest_tsv="${OUTPUT_DIR}/manifests/atlas_checked_file_manifest.tsv" \
  --download_log_tsv="${OUTPUT_DIR}/manifests/atlas_download_log.tsv" \
  --downloaded_files_tsv="${OUTPUT_DIR}/manifests/atlas_downloaded_files.tsv" \
  --force_download="${FORCE_DOWNLOAD}" \
  --require_expression_matrix="${REQUIRE_EXPRESSION_MATRIX}" \
  --expression_file_types="${EXPRESSION_FILE_TYPES}" \
  --timeout_seconds="${TIMEOUT_SECONDS}" \
  --retries="${RETRIES}"
