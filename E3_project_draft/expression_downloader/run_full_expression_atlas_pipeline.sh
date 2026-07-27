#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="/home/pthorpe001/data/2026_E3_protac/expression_downloader"
PROJECT_DIR="/home/pthorpe001/data/2026_E3_protac"
OUTPUT_DIR="${PROJECT_DIR}/analysis/expression_atlas_ftp_full"

CONDA_ENV="expression_downloaderR"

SPECIES_FILE="${REPO_DIR}/data/species.txt"
OVERRIDE_TSV="${REPO_DIR}/data/species_overrides.tsv"

DOWNLOAD_MANIFEST="${OUTPUT_DIR}/manifests/atlas_downloaded_files.tsv"
DUCKDB_PATH="${OUTPUT_DIR}/e3_expression.duckdb"

FORCE_DOWNLOAD="false"
FORCE_EXPRESSION_IMPORT="true"
FORCE_METADATA_IMPORT="true"
INCLUDE_OPTIONAL_EXTRAS="false"

TIMEOUT_SECONDS="30"
RETRIES="2"
CHUNK_ROWS="250000"

LOG_DIR="${OUTPUT_DIR}/logs"
RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/expression_atlas_full_pipeline_${RUN_STAMP}.log"

mkdir -p "${LOG_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "Started Expression Atlas full pipeline: $(date)"
echo "Repository: ${REPO_DIR}"
echo "Project directory: ${PROJECT_DIR}"
echo "Output directory: ${OUTPUT_DIR}"
echo "Log file: ${LOG_FILE}"


cd "${REPO_DIR}"

echo "Installing local R package"
R CMD INSTALL .

echo "Running R unit tests"
Rscript inst/scripts/08_run_tests.R

echo "Running Python unit tests"
./inst/scripts/09_run_python_tests.sh

echo "Running Expression Atlas discovery and download"
./inst/scripts/02_python_discover_download_atlas.sh \
    --species_file="${SPECIES_FILE}" \
    --override_tsv="${OVERRIDE_TSV}" \
    --output_dir="${OUTPUT_DIR}" \
    --force_download="${FORCE_DOWNLOAD}" \
    --timeout_seconds="${TIMEOUT_SECONDS}" \
    --retries="${RETRIES}" \
    --include_optional_extras="${INCLUDE_OPTIONAL_EXTRAS}"

echo "Importing expression TPM/FPKM matrices to Parquet"
./inst/scripts/04_python_import_expression_to_parquet.sh \
    --downloaded_files_tsv="${DOWNLOAD_MANIFEST}" \
    --output_dir="${OUTPUT_DIR}" \
    --force_import="${FORCE_EXPRESSION_IMPORT}" \
    --chunk_rows="${CHUNK_ROWS}"

echo "Importing sample metadata to Parquet"
./inst/scripts/05_python_import_sample_metadata_to_parquet.sh \
    --downloaded_files_tsv="${DOWNLOAD_MANIFEST}" \
    --output_dir="${OUTPUT_DIR}" \
    --force_import="${FORCE_METADATA_IMPORT}"

echo "Rebuilding DuckDB view database"
rm -f "${DUCKDB_PATH}"
rm -f "${DUCKDB_PATH}.wal"

Rscript inst/scripts/06_create_duckdb_views.R \
    --output_dir="${OUTPUT_DIR}" \
    --duckdb_path="${DUCKDB_PATH}"

echo "Final output summary"
echo "Expression import summary:"
ls -lh "${OUTPUT_DIR}/manifests/atlas_expression_import_summary.tsv"

echo "Metadata import summary:"
ls -lh "${OUTPUT_DIR}/manifests/atlas_sample_metadata_import_summary.tsv"

echo "DuckDB:"
ls -lh "${DUCKDB_PATH}"

echo "Parquet file count:"
find "${OUTPUT_DIR}/parquet" -name "*.parquet" | wc -l

echo "Finished Expression Atlas full pipeline: $(date)"
