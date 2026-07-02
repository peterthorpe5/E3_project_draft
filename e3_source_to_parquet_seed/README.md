# E3 PROTAC source-first Parquet/DuckDB rebuild

Version: **0.3.0**

This package builds a clean, auditable data layer from the selected inherited E3/PROTAC files.
It deliberately starts from the copied source files rather than blindly converting the inherited SQLite database.
The SQLite database is treated as a useful reference and regression target, not as the authoritative source of truth.

The current workflow is:

```text
raw_inherited_selected/
    ↓
source-preserving Parquet tables
    ↓
DuckDB views over every usable Parquet file
    ↓
curated E3 interrogation views
    ↓
Shiny app / downstream analysis
```

The key idea is to keep **two layers**:

1. **Source-preserving layer**: one Parquet table per source file or source sheet, with all original columns preserved as far as possible.
2. **Curated interrogation layer**: standardised DuckDB views such as `protein_records`, `protein_sequences`, `literature_evidence`, `go_term_evidence`, `ligandability_pocket_scores`, and `candidate_e3_summary`.

This makes the project easier to debug. If a curated field looks wrong, we can trace it back to the original inherited file, row, sheet, checksum and ingestion time.

---

## What v0.3 adds

Version 0.3 extends the earlier source-conversion package with a proper curated resource build.

New in this version:

- Creates curated DuckDB views for interrogation:
  - `protein_records`
  - `protein_sequences`
  - `literature_evidence`
  - `go_term_evidence`
  - `ligandability_pocket_scores`
  - `deepclust_cluster_evidence`
  - `sqlite_regression_query_results`
  - `expression_resource_status`
  - `candidate_e3_summary`
- Materialises those curated views to `derived/curated_parquet/` by default.
- Writes a verbose debug log and debug report:
  - `derived/logs/e3_build_curated_resource.log`
  - `derived/qc/curated_resource_debug.tsv`
  - `derived/qc/curated_resource_debug.md`
- Inspects the optional Expression Atlas/RNAseq DuckDB and records whether it was supplied and what objects it contains.
- Runs old inherited SQL example queries against the original SQLite DB as a regression reference.
- Writes a human-readable files-used report:
  - `derived/docs/FILES_USED_AND_CURATED_VIEWS.md`
- Expands the unit test suite to **54 tests**.

---

## Why not one giant Parquet file?

Do **not** collapse everything into one large Parquet file.

The inherited project contains different data types:

- E3 ligase protein records.
- FASTA sequences.
- literature-derived E3 evidence.
- GO/ubiquitination evidence.
- pocket and ligandability predictions.
- DeepClust outputs.
- SQL query examples.
- SQLite reference database.
- Expression Atlas/RNAseq data held separately.

These should remain as separate Parquet/DuckDB layers. The joined views should be made in DuckDB. This is much safer because each layer can be updated independently.

Examples:

```text
new expression/RNAseq data      → update expression resource only
new pocket predictions          → update ligandability layer only
new Orthofinder run             → update orthology/HOG layer later
new species/proteome            → append protein/sequence/orthogroup partitions
new literature evidence         → update literature_evidence only
```

---

## Expected project layout

Run this package against the curated working copy, not the full inherited external drive.

Expected input layout:

```text
E3_PROTAC_curated_working_copy_YYYYMMDD_HHMMSS/
├── raw_inherited_selected/
└── derived/
```

Expected output layout after running the full pipeline:

```text
E3_PROTAC_curated_working_copy_YYYYMMDD_HHMMSS/
├── raw_inherited_selected/
├── derived/
│   ├── parquet/
│   │   ├── source_tables/
│   │   ├── sequences/
│   │   ├── text/
│   │   └── inherited_parquet/
│   ├── curated_parquet/
│   │   ├── protein_records.parquet
│   │   ├── protein_sequences.parquet
│   │   ├── literature_evidence.parquet
│   │   ├── go_term_evidence.parquet
│   │   ├── ligandability_pocket_scores.parquet
│   │   ├── deepclust_cluster_evidence.parquet
│   │   ├── sqlite_regression_query_results.parquet
│   │   ├── expression_resource_status.parquet
│   │   └── candidate_e3_summary.parquet
│   ├── duckdb/
│   │   └── e3_protac_resource.duckdb
│   ├── qc/
│   │   ├── source_file_manifest.tsv
│   │   ├── tabular_table_catalog.tsv
│   │   ├── fasta_table_catalog.tsv
│   │   ├── text_file_catalog.tsv
│   │   ├── copied_existing_parquet_catalog.tsv
│   │   ├── sqlite_regression_query_results.tsv
│   │   ├── expression_resource_status.tsv
│   │   ├── curated_resource_debug.tsv
│   │   └── curated_resource_debug.md
│   ├── logs/
│   │   ├── e3_convert_seed_sources.log
│   │   ├── e3_create_duckdb_views.log
│   │   ├── e3_build_curated_resource.log
│   │   └── e3_write_files_used_report.log
│   └── docs/
│       └── FILES_USED_AND_CURATED_VIEWS.md
```

---

## Installation

Use the existing conda/R environment if it already has Python, pandas, pyarrow, openpyxl and DuckDB.
Otherwise:

```bash
conda install -c conda-forge pandas pyarrow openpyxl duckdb python-duckdb
```

Then run tests:

```bash
cd /path/to/e3_source_to_parquet_seed_v0_3
python -m unittest discover -s tests -v
```

Expected result for this release:

```text
Ran 54 tests

OK
```

---

## Full pipeline command

Basic run:

```bash
PROJECT_ROOT="/Volumes/ExtremeSSD/E3_PROTAC_curated_working_copy_20260702_105742"

cd /path/to/e3_source_to_parquet_seed_v0_3
./run_e3_seed_pipeline.sh "${PROJECT_ROOT}"
```

Run with the separate Expression Atlas/RNAseq DuckDB path:

```bash
PROJECT_ROOT="/Volumes/ExtremeSSD/E3_PROTAC_curated_working_copy_20260702_105742"
EXPRESSION_DUCKDB="/home/pthorpe001/data/2026_E3_protac/analysis/expression_atlas_ftp_full/e3_expression.duckdb"

cd /path/to/e3_source_to_parquet_seed_v0_3
./run_e3_seed_pipeline.sh "${PROJECT_ROOT}" "${EXPRESSION_DUCKDB}"
```

The expression/RNAseq data are **not automatically merged into the E3 source-first resource**. They are still a separate resource. This script records whether the expression DuckDB exists and what objects it contains in:

```text
derived/qc/expression_resource_status.tsv
derived/qc/expression_resource_status.parquet
derived/curated_parquet/expression_resource_status.parquet
```

This is intentional. The expression table is very large and should not be copied into the E3 resource unless we deliberately decide to do so. The Shiny app should use `E3_EXPRESSION_DUCKDB` for expression-specific tabs.

---

## Running steps individually

### 1. Build source manifest

```bash
python scripts/e3_build_manifest.py \
  --raw-root "${PROJECT_ROOT}/raw_inherited_selected" \
  --out-tsv "${PROJECT_ROOT}/derived/qc/source_file_manifest_preconversion.tsv"
```

### 2. Convert selected source files to source-preserving Parquet

```bash
python scripts/e3_convert_seed_sources.py \
  --raw-root "${PROJECT_ROOT}/raw_inherited_selected" \
  --out-dir "${PROJECT_ROOT}/derived" \
  --copy-existing-parquet
```

This creates:

```text
derived/parquet/source_tables/
derived/parquet/sequences/
derived/parquet/text/
derived/parquet/inherited_parquet/
```

It also writes catalogue files in `derived/qc/`.

### 3. Clean macOS sidecar files

```bash
python scripts/e3_clean_macos_sidecars.py \
  --root "${PROJECT_ROOT}/derived" \
  --out-tsv "${PROJECT_ROOT}/derived/qc/macos_sidecar_deleted.tsv" \
  --delete
```

This removes files such as `._concated_seqs.parquet`. These are AppleDouble/macOS sidecar files, not real data files.

### 4. Create DuckDB views over all source-preserving Parquet files

```bash
python scripts/e3_create_duckdb_views.py \
  --derived-dir "${PROJECT_ROOT}/derived" \
  --duckdb-path "${PROJECT_ROOT}/derived/duckdb/e3_protac_resource.duckdb"
```

This creates one DuckDB view per usable Parquet file and stores the list in `parquet_view_catalog`.

### 5. Build curated E3 interrogation views

```bash
python scripts/e3_build_curated_resource.py \
  --raw-root "${PROJECT_ROOT}/raw_inherited_selected" \
  --derived-dir "${PROJECT_ROOT}/derived" \
  --duckdb-path "${PROJECT_ROOT}/derived/duckdb/e3_protac_resource.duckdb" \
  --expression-duckdb "${EXPRESSION_DUCKDB}"
```

The `--expression-duckdb` argument is optional but recommended for debugging the Shiny expression/RNAseq connection.

### 6. Write the files-used document

```bash
python scripts/e3_write_files_used_report.py \
  --derived-dir "${PROJECT_ROOT}/derived" \
  --output "${PROJECT_ROOT}/derived/docs/FILES_USED_AND_CURATED_VIEWS.md"
```

---

## Curated DuckDB views

### `protein_records`

Best-effort standardised protein-level table built from the selected E3 ligase source table.

Adds standard columns where possible:

- `protein_accession`
- `gene_names_standardised`
- `organism_standardised`
- `organism_id_standardised`
- `e3_category_standardised`
- `reviewed_standardised`
- `protein_names_standardised`
- `protein_length_standardised`
- `embedded_sequence`
- `embedded_sequence_md5`
- `_curated_source_view`

It also keeps all original source columns.

### `protein_sequences`

Sequence table built from parsed FASTA sources.

Standard columns:

- `protein_accession`
- `sequence_header`
- `sequence`
- `sequence_length`
- `sequence_md5`
- `_curated_source_view`

Large FASTA files are skipped by default during source conversion unless explicitly enabled. Skipped large FASTA files are recorded in `derived/qc/fasta_table_catalog.tsv`.

### `literature_evidence`

Union-by-name view over inherited literature and literature-mapping files. It is deliberately permissive and heterogeneous at this stage.

Standard columns:

- `protein_accession`
- `paper_or_publication_id`
- `_curated_source_view`

All original columns are retained.

### `go_term_evidence`

GO/ubiquitination evidence from GO source files and any GO-related columns present in E3 ligase tables.

Standard columns:

- `protein_accession`
- `go_id_or_terms`
- `ubiquitin_go_term_flag`
- `exclusion_go_term_flag`
- `_curated_source_view`

### `ligandability_pocket_scores`

Union-by-name view over pocket, druggability, fpocket, P2Rank, AF2BIND and candidate-output files.

Standard columns:

- `protein_accession`
- `pocket_name_standardised`
- `druggability_score_numeric`
- `probability_numeric`
- `pocket_rank_numeric`
- `p2rank_score_numeric`
- `_curated_source_view`

All original columns are retained.

### `deepclust_cluster_evidence`

Exploratory view over DeepClust output files that were included in the curated copy.

This is **not the final Orthofinder/HOG layer**. Orthofinder should be added later as its own explicit import.

Standard columns:

- `protein_accession`
- `cluster_or_orthogroup_id`
- `_curated_source_view`

### `sqlite_regression_query_results`

Regression-only view. This records which old SQL queries ran against the inherited SQLite database and what row/column counts they returned.

It does **not** mean SQLite is being treated as the source of truth. It is being used as a reference to help check that the source-first rebuild has not lost important historical behaviour.

Standard columns include:

- `query_id`
- `source_file`
- `query_index`
- `sql_text`
- `sqlite_status`
- `sqlite_row_count`
- `sqlite_column_count`
- `sqlite_columns_json`
- `sqlite_error`
- `duckdb_equivalent_status`

### `expression_resource_status`

Diagnostic view for the separate expression/RNAseq resource.

This is there because expression/RNAseq data can be missed if the Shiny app is only pointed at the E3 resource DuckDB.

Possible statuses:

- `not_provided`: no expression path was supplied.
- `missing_file`: the supplied path does not exist.
- `duckdb_not_installed`: cannot inspect because DuckDB Python package is missing.
- `found`: object found in expression DuckDB.
- `failed`: attempted inspection but failed.

### `candidate_e3_summary`

Compact query-friendly summary joining evidence counts and key scores back to `protein_records`.

Includes:

- protein accession, gene, organism, category and reviewed status.
- sequence evidence count and representative sequence checksum.
- ligandability evidence count.
- maximum druggability score.
- maximum pocket probability.
- best pocket rank.
- GO evidence count.
- ubiquitination GO flag.
- literature evidence count.
- DeepClust evidence count.
- binary flags for sequence, ligandability and literature evidence.

This is the table the Shiny app should eventually use for high-level E3 filtering.

---

## Debugging outputs

The most important file is:

```text
derived/qc/curated_resource_debug.md
```

This tells you:

- whether the source Parquet view catalogue was found;
- which source table was used for `protein_records`;
- how many rows each curated view contains;
- whether ligandability, GO, literature, DeepClust, expression and SQLite regression layers were found;
- which curated Parquet files were exported;
- whether any step failed.

The full Python traceback, if there is one, is written to:

```text
derived/logs/e3_build_curated_resource.log
```

The human-readable run document is:

```text
derived/docs/FILES_USED_AND_CURATED_VIEWS.md
```

---

## Example DuckDB queries

Open the resource:

```bash
duckdb "${PROJECT_ROOT}/derived/duckdb/e3_protac_resource.duckdb"
```

Show curated views:

```sql
SELECT * FROM curated_view_catalog;
```

Inspect candidate summary:

```sql
SELECT
  protein_accession,
  organism_standardised,
  e3_category_standardised,
  max_druggability_score,
  max_pocket_probability,
  best_pocket_rank,
  literature_record_count,
  has_ubiquitin_go_term
FROM candidate_e3_summary
ORDER BY max_druggability_score DESC NULLS LAST,
         max_pocket_probability DESC NULLS LAST
LIMIT 50;
```

Check Arabidopsis records:

```sql
SELECT *
FROM candidate_e3_summary
WHERE organism_id_standardised = '3702'
LIMIT 50;
```

Check expression/RNAseq status:

```sql
SELECT * FROM expression_resource_status;
```

Check old SQLite query results:

```sql
SELECT source_file, query_id, sqlite_status, sqlite_row_count, sqlite_error
FROM sqlite_regression_query_results
ORDER BY source_file, query_index;
```

---

## Orthofinder status

Orthofinder/HOG integration is still deliberately separate.

Do not fold Orthofinder into this source-first E3 layer until we have identified and copied the correct Orthofinder outputs. Later we should add:

- `orthogroup_members`
- `hog_members`
- `orthogroup_species_counts`
- `hog_species_counts`
- `orthogroup_sequences`
- `orthofinder_run_metadata`

Those should become a separate import layer with its own tests and debug report.

---

## Development standards

All new Python code should remain:

- unit tested with `unittest`;
- PEP 8 style;
- defensive about missing files and missing columns;
- explicit about provenance;
- verbose in log files;
- careful not to silently merge unrelated source tables;
- careful not to treat inherited SQLite as ground truth.

The same standards should be used for any future R code.
