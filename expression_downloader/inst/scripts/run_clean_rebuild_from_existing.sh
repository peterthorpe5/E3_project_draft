#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_MANIFEST=""
RAW_ROOT=""
OUTPUT_DIR=""
DOWNLOAD_MISSING_CONFIGURATION="true"
TIMEOUT_SECONDS="30"
RETRIES="2"
CHUNK_ROWS="250000"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source_manifest=*) SOURCE_MANIFEST="${1#*=}"; shift ;;
    --source_manifest) SOURCE_MANIFEST="$2"; shift 2 ;;
    --raw_root=*) RAW_ROOT="${1#*=}"; shift ;;
    --raw_root) RAW_ROOT="$2"; shift 2 ;;
    --output_dir=*) OUTPUT_DIR="${1#*=}"; shift ;;
    --output_dir) OUTPUT_DIR="$2"; shift 2 ;;
    --download_missing_configuration=*)
      DOWNLOAD_MISSING_CONFIGURATION="${1#*=}"
      shift
      ;;
    --download_missing_configuration)
      DOWNLOAD_MISSING_CONFIGURATION="$2"
      shift 2
      ;;
    --timeout_seconds=*) TIMEOUT_SECONDS="${1#*=}"; shift ;;
    --timeout_seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --retries=*) RETRIES="${1#*=}"; shift ;;
    --retries) RETRIES="$2"; shift 2 ;;
    --chunk_rows=*) CHUNK_ROWS="${1#*=}"; shift ;;
    --chunk_rows) CHUNK_ROWS="$2"; shift 2 ;;
    *) printf 'ERROR: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

if [[ -z "${SOURCE_MANIFEST}" || -z "${RAW_ROOT}" || -z "${OUTPUT_DIR}" ]]; then
  printf '%s\n' \
    'ERROR: --source_manifest, --raw_root and --output_dir are required.' >&2
  exit 2
fi
if [[ "${SOURCE_MANIFEST}" != /* || "${RAW_ROOT}" != /* || "${OUTPUT_DIR}" != /* ]]; then
  printf '%s\n' 'ERROR: all source and output paths must be absolute.' >&2
  exit 2
fi
if [[ ! -s "${SOURCE_MANIFEST}" ]]; then
  printf 'ERROR: source manifest is missing or empty: %s\n' \
    "${SOURCE_MANIFEST}" >&2
  exit 1
fi
if [[ ! -d "${RAW_ROOT}/downloads" ]]; then
  printf 'ERROR: raw download tree is missing: %s\n' \
    "${RAW_ROOT}/downloads" >&2
  exit 1
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
  printf 'ERROR: clean rebuild output already exists: %s\n' \
    "${OUTPUT_DIR}" >&2
  exit 1
fi
if [[ "${OUTPUT_DIR}" == "${RAW_ROOT}" ]]; then
  printf '%s\n' 'ERROR: the rebuild output must differ from the raw root.' >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PREPARED_MANIFEST="${OUTPUT_DIR}/manifests/atlas_downloaded_files_strict.tsv"
DUCKDB_PATH="${OUTPUT_DIR}/e3_expression.duckdb"

CURRENT_STAGE="initialisation"
trap 'printf "ERROR: clean rebuild failed during %s. Output retained at: %s\n" \
  "${CURRENT_STAGE}" "${OUTPUT_DIR}" >&2' ERR

mkdir -p "${OUTPUT_DIR}/manifests"
cp -p -- \
  "${SOURCE_MANIFEST}" \
  "${OUTPUT_DIR}/manifests/source_atlas_downloaded_files.tsv"

CURRENT_STAGE="legacy source preparation"
"${SCRIPT_DIR}/03_prepare_existing_atlas_downloads.sh" \
  --source_manifest "${SOURCE_MANIFEST}" \
  --raw_root "${RAW_ROOT}" \
  --supplement_root "${OUTPUT_DIR}/raw_supplements" \
  --output_manifest "${PREPARED_MANIFEST}" \
  --download_missing_configuration "${DOWNLOAD_MISSING_CONFIGURATION}" \
  --timeout_seconds "${TIMEOUT_SECONDS}" \
  --retries "${RETRIES}"

# Metadata is deliberately validated before the much larger expression import.
CURRENT_STAGE="configuration-backed metadata import"
"${SCRIPT_DIR}/05_python_import_sample_metadata_to_parquet.sh" \
  --downloaded_files_tsv "${PREPARED_MANIFEST}" \
  --output_dir "${OUTPUT_DIR}" \
  --force_import false

CURRENT_STAGE="expression matrix import"
"${SCRIPT_DIR}/04_python_import_expression_to_parquet.sh" \
  --downloaded_files_tsv "${PREPARED_MANIFEST}" \
  --output_dir "${OUTPUT_DIR}" \
  --force_import false \
  --chunk_rows "${CHUNK_ROWS}"

CURRENT_STAGE="validated DuckDB publication"
"${SCRIPT_DIR}/06_python_create_duckdb_views.sh" \
  --output_dir "${OUTPUT_DIR}" \
  --duckdb_path "${DUCKDB_PATH}" \
  --force false

trap - ERR
printf 'Clean Expression Atlas rebuild completed: %s\n' "${OUTPUT_DIR}"
printf 'Validated DuckDB: %s\n' "${DUCKDB_PATH}"
