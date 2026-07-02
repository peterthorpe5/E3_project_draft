# E3 PROTAC Resource Shiny app

This is the Shiny front end for the E3 PROTAC project resource. It now supports two related data layers:

1. **Source-first E3 PROTAC resource**: a DuckDB database built over the curated source-first Parquet rebuild of the inherited Erin Butterfield / Drost lab files.
2. **Expression Atlas resource**: the existing DuckDB database produced by the separate Expression Atlas downloader/import pipeline.

The app should remain thin. It should query DuckDB views, display bounded result sets, and avoid importing large source tables into R memory.

## Why this version exists

The inherited folder structure contains useful data, but the original folder names are not clear and the SQLite database should not be treated as the only source of truth. The current project direction is therefore:

```text
curated inherited source files
  -> source-preserving Parquet tables
  -> DuckDB views
  -> Shiny resource browser and later curated biological views
```

The app in this package is version **0.3.0**. It adds a generic browser for the source-first Parquet/DuckDB resource before we commit to the final biological schema.

## What the app can currently do

### Source-first resource tabs

The new source-first tabs are:

- **Resource overview**: lists the DuckDB views created over the source-first Parquet files.
- **Browse resource tables**: lets you choose any resource view and preview a bounded number of rows.
- **Files used**: displays the source manifest and conversion catalogs written by the source-to-Parquet pipeline.

These tabs are deliberately generic because the inherited data are still being audited. They make it possible to inspect all converted source tables without guessing which table is biologically final.

### Expression tabs

The existing Expression Atlas tabs are retained:

- **Expression summary**
- **Expression table**
- **Gene lookup**
- **Visualise expression**

These still expect the Expression Atlas DuckDB views:

- `atlas_expression_long`
- `atlas_sample_metadata_wide_joinable`
- `atlas_expression_with_sample_metadata`

## Configuration

You can configure the app with environment variables or command-line arguments. Command-line arguments take priority.

| Purpose | Environment variable | Command-line argument |
|---|---|---|
| Source-first E3 resource DuckDB | `E3_RESOURCE_DUCKDB` | `--resource_duckdb_path` |
| Source-first derived directory | `E3_RESOURCE_DERIVED_DIR` | `--resource_derived_dir` |
| Expression Atlas DuckDB | `E3_EXPRESSION_DUCKDB` | `--expression_duckdb_path` |
| Maximum preview rows | `E3_MAX_TABLE_ROWS` | `--max_table_rows` |
| Default expression unit | `E3_DEFAULT_EXPRESSION_UNIT` | `--default_expression_unit` |
| Shiny host | `E3_SHINY_HOST` | `--host` |
| Shiny port | `E3_SHINY_PORT` | `--port` |

Example:

```bash
PROJECT_ROOT="/Volumes/ExtremeSSD/E3_PROTAC_curated_working_copy_20260702_105742"

export E3_RESOURCE_DUCKDB="${PROJECT_ROOT}/derived/duckdb/e3_protac_resource.duckdb"
export E3_RESOURCE_DERIVED_DIR="${PROJECT_ROOT}/derived"
export E3_EXPRESSION_DUCKDB="/home/pthorpe001/data/2026_E3_protac/analysis/expression_atlas_ftp_full/e3_expression.duckdb"
export E3_MAX_TABLE_ROWS=1000

./run_app.sh --host 127.0.0.1 --port 3838
```

Equivalent direct command:

```bash
Rscript inst/scripts/run_app.R \
  --resource_duckdb_path "${PROJECT_ROOT}/derived/duckdb/e3_protac_resource.duckdb" \
  --resource_derived_dir "${PROJECT_ROOT}/derived" \
  --expression_duckdb_path "/home/pthorpe001/data/2026_E3_protac/analysis/expression_atlas_ftp_full/e3_expression.duckdb" \
  --host 127.0.0.1 \
  --port 3838
```

## Generate the files-used document

The app includes a script that writes a persistent Markdown document describing the files used in the current source-first build:

```bash
PROJECT_ROOT="/Volumes/ExtremeSSD/E3_PROTAC_curated_working_copy_20260702_105742"

Rscript inst/scripts/write_data_sources_report.R \
  --derived_dir "${PROJECT_ROOT}/derived" \
  --output "${PROJECT_ROOT}/derived/docs/FILES_USED.md" \
  --max_rows 1000
```

The report includes:

- source-file manifest summary;
- tabular files converted to Parquet;
- FASTA files converted or skipped;
- text/SQL files preserved line-by-line;
- inherited Parquet files copied into the source-first layer;
- DuckDB view catalog;
- notes on macOS sidecar files and deferred Orthofinder import.

This is the document to keep with the dataset when handing it to someone else.

## Install/check dependencies

The app expects these R packages:

```bash
conda install -c conda-forge \
  r-base r-shiny r-bslib r-dplyr r-dt r-ggplot2 r-plotly \
  r-rlang r-shinycssloaders r-stringr r-tibble r-testthat \
  r-duckdb duckdb
```

Then check dependencies:

```bash
Rscript inst/scripts/check_dependencies.R
```

## Run tests

```bash
Rscript inst/scripts/run_tests.R
```

The tests cover:

- command-line/config parsing;
- SQL helper construction;
- expression query helpers;
- resource DuckDB helper queries;
- resource UI modules;
- source-file report generation;
- small DuckDB integration tests where `duckdb`, `DBI`, and `duckplyr` are installed.

## Current limitations

This version is not yet the final biological E3 prioritisation app. It is the safe inspection layer.

Still to build:

1. `protein_records` curated view.
2. `protein_sequences` curated view.
3. `literature_evidence` curated view.
4. `go_term_evidence` curated view.
5. `ligandability_pocket_scores` curated view.
6. `candidate_e3_summary` curated view.
7. Orthofinder/HOG import and sequence extraction layer.
8. Structural alignment and pocket-conservation layer.
9. Expression overlay against protein/gene identifiers.

The important principle is not to merge everything into one huge Parquet file. Keep source-derived tables separate, carry provenance columns forward, and use DuckDB views for joins and Shiny queries.

## Production rules

- Do not collect whole resource tables into R.
- Keep all previews row-limited.
- Keep source file, checksum, source sheet, original row number, and inherited path metadata wherever possible.
- Use the inherited SQLite database for regression checks, not as the only data source.
- Keep Orthofinder as a separate import step because those folders are large and need a focused schema.
